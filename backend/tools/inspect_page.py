"""
Show what the agent can see and act on for a given URL.

Runs the real snapshot and targeting code without the LLM or the graph, so you can
tell in seconds whether a page is workable and, if not, which layer is at fault.
That distinction is otherwise buried in a full agent run.

Usage, from backend/:

    python tools/inspect_page.py https://example.com/apply
    python tools/inspect_page.py https://example.com/apply --headed --wait 5

What to look for:

  * "main frame elements: 0" means the snapshot is broken, not the model.
  * A field in the form inventory that is missing from the snapshot cannot be
    addressed by the agent at all.
  * "UNADDRESSABLE" targets are advertised to the model but do not resolve, which
    is what makes it retry the same failing action.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from playwright.async_api import async_playwright  # noqa: E402

from agents.executor import Executor  # noqa: E402
from execution import actions  # noqa: E402
from execution.targeting import element_inventory, resolve_target, unique_frames  # noqa: E402


ACTIONABLE = {"button", "link", "textbox", "searchbox", "combobox", "checkbox", "radio", "option", "tab", "menuitem"}


def rule(title: str) -> None:
    print()
    print(f"--- {title} " + "-" * max(0, 66 - len(title)))


async def inspect(url: str, headed: bool, wait: float) -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            print(f"Could not load {url}: {type(exc).__name__}: {exc}")
            await browser.close()
            return 1

        if wait:
            await page.wait_for_timeout(int(wait * 1000))

        print(f"URL     {page.url}")
        print(f"TITLE   {(await page.title())[:70]}")
        print(f"FRAMES  {len(unique_frames(page))}")

        # --- what the model is shown -------------------------------------
        executor = Executor.__new__(Executor)
        snapshot = await executor._get_real_dom_snapshot(page, max_chars=5200)
        lines = [l for l in snapshot.splitlines() if l.startswith('[role=')]
        main_count = 0
        for line in snapshot.splitlines():
            if line.startswith("[iframe"):
                break
            if line.startswith("[role="):
                main_count += 1

        rule("SNAPSHOT (what the model sees)")
        if "DOM snapshot failed" in snapshot:
            print("  BROKEN:", next(l for l in snapshot.splitlines() if "failed" in l))
        print(f"  main frame elements: {main_count}")
        print(f"  total elements:      {len(lines)}")
        print(f"  characters:          {len(snapshot)} (budget 5200)")
        if len(snapshot) >= 5200:
            print("  TRUNCATED: fields near the end of the page are not visible to the agent.")
        for line in lines[:15]:
            print("   ", line[:92])
        if len(lines) > 15:
            print(f"    ... {len(lines) - 15} more")

        # --- form inventory ----------------------------------------------
        rule("read_form (field state the agent can query)")
        form = await actions.do_read_form(page)
        print(f"  {form.message}")
        for line in (form.extracted_text or "").splitlines()[1:26]:
            print("   ", line[:92])

        # --- can every advertised target actually be resolved? -----------
        rule("ADDRESSABILITY (advertised targets that actually resolve)")
        inventory = [c for c in await element_inventory(page, limit=200) if c.role in ACTIONABLE]
        checked = 0
        bad: list[str] = []
        ambiguous: list[str] = []
        for cand in inventory[:60]:
            res = await resolve_target(page, cand.role, cand.name)
            checked += 1
            if res.error == "ambiguous_target":
                ambiguous.append(f"{cand.role} \"{cand.name}\" ({res.match_count} matches)")
            elif not res.ok:
                bad.append(f"{cand.role} \"{cand.name}\" -> {res.error}")
        print(f"  checked {checked} target(s)")
        print(f"  resolve cleanly:  {checked - len(bad) - len(ambiguous)}")
        print(f"  need nth=:        {len(ambiguous)}")
        print(f"  UNADDRESSABLE:    {len(bad)}")
        for item in ambiguous[:8]:
            print(f"    ambiguous: {item}")
        for item in bad[:8]:
            print(f"    BROKEN:    {item}")

        # --- capability coverage -----------------------------------------
        rule("CAPABILITY CHECK")
        counts: dict[str, int] = {}
        for frame in unique_frames(page):
            for label, selector in (
                ("file inputs", "input[type='file']"),
                ("selects", "select"),
                ("checkboxes", "input[type='checkbox']"),
                ("radios", "input[type='radio']"),
                ("date inputs", "input[type='date']"),
                ("iframes", "iframe"),
            ):
                try:
                    counts[label] = counts.get(label, 0) + await frame.locator(selector).count()
                except Exception:
                    pass
        for label, n in counts.items():
            note = ""
            if label == "date inputs" and n:
                note = "  <- no dedicated primitive yet"
            print(f"  {label:14} {n}{note}")

        await browser.close()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Show what the agent can see and act on for a URL.")
    parser.add_argument("url")
    parser.add_argument("--headed", action="store_true", help="show the browser")
    parser.add_argument("--wait", type=float, default=2.0, help="seconds to settle after load")
    args = parser.parse_args()
    return asyncio.run(inspect(args.url, args.headed, args.wait))


if __name__ == "__main__":
    raise SystemExit(main())
