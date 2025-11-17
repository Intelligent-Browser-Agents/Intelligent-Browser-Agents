"""
Playwright browser context and session manager
"""

import asyncio
from typing import Dict, Optional
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


class BrowserManager:
    """Manages browser sessions and contexts"""
    
    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.contexts: Dict[str, BrowserContext] = {}
        self.pages: Dict[str, Dict[int, Page]] = {}  # session_id -> {tab_index -> page}
        self.current_tab: Dict[str, int] = {}  # session_id -> current_tab_index
        self._lock = asyncio.Lock()
    
    async def initialize(self):
        """Initialize playwright and browser"""
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                slow_mo=1000,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
    
    async def get_or_create_context(self, session_id: str) -> BrowserContext:
        """Get or create a browser context for a session"""
        async with self._lock:
            if session_id not in self.contexts:
                await self.initialize()
                user_data_dir = Path(f"/tmp/ig_sessions/{session_id}")
                user_data_dir.mkdir(parents=True, exist_ok=True)
                
                self.contexts[session_id] = await self.browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    viewport={'width': 1280, 'height': 720},
                    ignore_https_errors=True
                )
                self.pages[session_id] = {}
                self.current_tab[session_id] = 0
            
            return self.contexts[session_id]
    
    async def get_or_create_page(self, session_id: str, tab_index: Optional[int] = None) -> Page:
        """Get or create a page (tab) in a session"""
        context = await self.get_or_create_context(session_id)
        
        if session_id not in self.pages:
            self.pages[session_id] = {}
        
        if tab_index is None:
            tab_index = self.current_tab.get(session_id, 0)
        
        if tab_index not in self.pages[session_id]:
            page = await context.new_page()
            self.pages[session_id][tab_index] = page
        
        self.current_tab[session_id] = tab_index
        return self.pages[session_id][tab_index]
    
    async def switch_tab(self, session_id: str, tab_index: int) -> Page:
        """Switch to a different tab"""
        if session_id in self.pages and tab_index in self.pages[session_id]:
            self.current_tab[session_id] = tab_index
            return self.pages[session_id][tab_index]
        else:
            # Create new tab if it doesn't exist
            return await self.get_or_create_page(session_id, tab_index)
    
    async def close_tab(self, session_id: str, tab_index: Optional[int] = None):
        """Close a tab"""
        if session_id not in self.pages:
            return
        
        if tab_index is None:
            tab_index = self.current_tab.get(session_id, 0)
        
        if tab_index in self.pages[session_id]:
            await self.pages[session_id][tab_index].close()
            del self.pages[session_id][tab_index]
            
            # Update current tab if needed
            if self.current_tab.get(session_id) == tab_index:
                remaining_tabs = list(self.pages[session_id].keys())
                if remaining_tabs:
                    self.current_tab[session_id] = min(remaining_tabs)
                else:
                    self.current_tab[session_id] = 0
    
    async def cleanup_session(self, session_id: str):
        """Clean up a specific session"""
        if session_id in self.contexts:
            await self.contexts[session_id].close()
            del self.contexts[session_id]
        
        if session_id in self.pages:
            del self.pages[session_id]
        
        if session_id in self.current_tab:
            del self.current_tab[session_id]
    
    async def cleanup(self):
        """Clean up all resources"""
        for session_id in list(self.contexts.keys()):
            await self.cleanup_session(session_id)
        
        if self.browser:
            await self.browser.close()
            self.browser = None
        
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None


browser_manager = BrowserManager()