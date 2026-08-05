---
name: job-application
description: Domain knowledge for filling and submitting online job applications - mapping arbitrary application questions to the user's stored profile, safe defaults for questions the profile does not cover, and tailoring rules for free-text answers. Keeps job-application semantics out of the generic agent prompts.
---

This skill holds the job-application domain knowledge for the browser agent.
The generic prompts know how to fill forms; this skill knows what job-application forms ask and how to answer them from the user's stored profile (personal info, experience entries, documents).

## Source of truth

- Answers come from the user's stored profile: personal info (name, email, phone, address), experience and education entries, and uploaded documents (resume, cover letter).
- Never fabricate an answer. If the profile does not cover a required question and no rule below provides a safe default, the correct move is to ask the user (request_context / requested_fields), not to guess.

## Question-mapping heuristics

Application forms ask the same questions under many labels. Map by meaning, not by exact label:

| Question pattern | Profile source |
| --- | --- |
| "Full name", "Legal name", "First/Last name" | personal info name (split on the form's granularity) |
| "Email", "Contact email" | personal info email |
| "Phone", "Mobile" | personal info phone |
| "Address", "City", "State", "ZIP/Postal", "Country" | personal info address, split per field |
| "Resume", "CV", "Attach your resume" | resume document via upload_file |
| "Cover letter" | cover-letter document if stored, else a tailored free-text answer (see Tailoring) |
| "Current/most recent employer", "Company" | most recent experience entry organization |
| "Job title", "Current role" | most recent experience entry title |
| "Years of experience" | computed from experience entry dates; round down, never up |
| "Education", "Degree", "School", "Graduation date" | education entries |
| "LinkedIn", "Website", "Portfolio", "GitHub" | profile links if stored; otherwise leave optional fields empty |
| "How did you hear about us", "Referral source" | "Job board" unless the user specified otherwise |
| "Earliest start date", "Notice period" | user-provided value; default "2 weeks" only if the user approved that default |

## Questions that must never be guessed

These have legal or eligibility consequences. Use the user's stored answer; if absent, stop and ask:

- Work authorization ("Are you authorized to work in ...?").
- Visa sponsorship ("Will you now or in the future require sponsorship?").
- Security clearance, professional licenses, certifications.
- Criminal history, background-check consent.
- Age / over-18 confirmation.
- Desired salary or salary expectations: ask the user; if the field is optional, prefer leaving it empty or "Negotiable" where free text is allowed.

## Voluntary self-identification (EEO)

Demographic sections (gender, race/ethnicity, veteran status, disability) are voluntary.
Unless the user has stored explicit answers, select the "Decline to self-identify" / "I don't wish to answer" option.
Never infer demographic answers from any other data.

## Tailoring rules for free-text answers

- "Why do you want to work here?" / "Tell us about yourself": 3-5 sentences built strictly from stored experience entries and the job listing's own language. Name the role and company from the listing; claim only skills and history present in the profile.
- Keep tailored text factual: no invented achievements, metrics, employers, or dates.
- Reuse the listing's key terms where they truthfully describe the user's experience (helps keyword screens without fabrication).
- If the field is optional and the profile gives nothing relevant to say, leave it empty rather than padding.

## Flow conventions

- Job applications are usually multi-page: contact info -> resume/experience -> questions -> self-identification -> review -> submit. Plan one page or section per step.
- Many ATS platforms parse the uploaded resume and prefill fields. After an upload, read the form before typing: correct wrong prefills instead of duplicating them.
- Use read_form before every Continue/Next/Submit to catch required fields the snapshot ranked below the fold.
- "Save and continue" is safe; the final "Submit application" is irreversible and goes through the autonomy policy's confirmation gate like any other irreversible action.
- The confirmation page (or confirmation email text) is the completion evidence; extract it so the run's result records that the application was actually submitted.

## Boundaries

- Account creation on an ATS ("create a profile to apply") is a login/registration flow, not part of this skill; it follows the system's credential rules.
- CAPTCHA and identity-verification challenges always go to the user.
- One application per work item; report per-item outcomes so a bulk run shows exactly which applications submitted.
