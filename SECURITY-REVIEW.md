# Talkative Production Readiness and Security Review

**Assessment date:** October 3, 2026  
**Scope:** Static review of repository deployment configuration, documented architecture, and the published Terms and Privacy Policy drafts. This is a launch-readiness assessment, not a penetration test, legal opinion, or certification. External hosting controls and runtime behavior were not verified.

## Security finding

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| 1 | 🟡 MEDIUM | `docker-compose.yml`, `talkative_backend/application.py` | 27–28; 13 | The Compose stack exposes the app over plain HTTP on all host interfaces, and the session cookie is not marked Secure. On an untrusted network, credentials or session cookies can be intercepted, including access to the admin transcript archive. No external TLS proxy or firewall was verified. | 9/10 |

**Required mitigation:** Put the app behind a trusted TLS-terminating reverse proxy, do not expose port 8000 publicly, restrict app ingress to that proxy, and enable Secure session cookies when deployed over HTTPS. Verify proxy handling, HTTPS redirects, HSTS, and forwarded-header trust before launch.

The security review found one concrete issue in repository deployment configuration. It could not verify whether infrastructure outside the repository already provides TLS or network restrictions.

## Other documented launch gaps

These are readiness gaps identified from the project notes and deployment documentation; they are not additional findings from the delegated security review.

- The project notes say CSRF protection and login/admin rate limits remain to be added. Add CSRF protection to state-changing browser endpoints and rate limits/abuse controls for login, signup, admin login, reporting, and chat operations.
- Email verification and password recovery are not implemented. Add verified account ownership and a safe recovery flow, or explicitly decide whether launch without them is acceptable.
- The deployment uses SQLite for user, admin, and live-chat state and supports one app instance. Keep the state database on persistent storage; do not scale multiple app instances over SQLite without validating locking/concurrency and migration behavior.
- The application holds account PII and active chat content in SQLite; ended transcripts are stored in the admin database for up to 24 hours. Define encryption, backup, access, expiry, and deletion behavior for every copy, including backups and migration volumes.
- Admin transcript access is high impact. Use a non-default, unique admin credential, restrict `/admin` to authorized operators, add MFA if feasible, review access audit events, and avoid broad production access.

## Indian law and compliance assessment

Talkative collects personal data and enables user-to-user chat. It is likely within the scope of India’s digital privacy and intermediary frameworks when offered to people in India, but counsel should confirm the entity’s role, territorial scope, and applicable obligations.

### Digital personal data

The Digital Personal Data Protection Act, 2023 and Digital Personal Data Protection Rules, 2025 are being brought into force in phases. The Rules were notified on November 13, 2025. The published schedule places Rule 4 on November 13, 2026 and the main substantive rules, including notice, safeguards, breach, rights, and retention requirements, on May 13, 2027. Confirm the Gazette commencement provisions and any later amendments with Indian privacy counsel before relying on these dates. Do not treat the later dates as a reason to defer design or preparation.

Talkative collects names, username, email, date of birth, gender, country, password hashes, optional profile information, account/activity records, moderation events, and chat transcripts. Phone numbers are not collected for account registration. The product should prepare to:

1. Maintain a data inventory that maps each field and message stream to its purpose, legal basis, storage location, processors, recipients, access roles, and retention/deletion trigger.
2. Replace broad or bundled consent language with clear, purpose-specific notices and valid consent flows where consent is the basis. Record notice/consent versions and timestamps, make withdrawal easy, and stop the related processing when required.
3. Implement a user-rights workflow for access, correction, erasure, grievance, and nomination requests, with identity verification, response ownership, deadlines, and auditable completion.
4. Publish the Data Fiduciary’s legal name and privacy/grievance contact. Make notices understandable and available at the point of collection.
5. Put written privacy/security terms in place with hosting, email, monitoring, analytics, and other processors. Inventory cross-border transfers and check restrictions or government requirements before selecting providers or regions.
6. Document appropriate security safeguards and a breach-response procedure, including assessment, escalation, evidence preservation, and notices to affected people and the Data Protection Board when required.
7. Define deletion schedules for account data, chat archives, audit events, logs, and backups. The existing “up to 24 hours” chat archive statement must match actual state database, admin database, backup, and operator-access behavior.
8. Keep evidence of consent, policy versions, user requests, retention/deletion jobs, access reviews, and incident exercises.

The DPDP Act defines a child as a person under 18. Talkative’s Terms require users to be at least 18, so enforce that rule during signup and prevent underage accounts from using chat; a terms-only restriction is not an effective age gate. Have counsel establish escalation and reporting procedures for credible child-safety or illegal-content reports.

Rule 4 concerns the Consent Manager framework. It appears relevant only if Talkative itself operates as a Consent Manager; the product description reviewed here does not indicate that it does. Confirm applicability rather than treating registration as an ordinary app requirement.

### Intermediary and online-safety obligations

Because users exchange messages through the service, Talkative may be an intermediary under the Information Technology Act, 2000 and the Information Technology (Intermediary Guidelines and Digital Media Ethics Code) Rules, 2021, as amended. Obtain an Indian legal classification. If the rules apply, establish and publish the required terms, prohibited-use rules, grievance contact and complaint handling, and a documented process for lawful orders and time-sensitive content complaints. The Rules generally require grievance acknowledgement within 24 hours and resolution within 15 days; specific complaint types have shorter action periods. Validate the current, amended text—including the February 2026 amendment—before setting operating SLAs. Do not assume the enhanced Significant Social Media Intermediary obligations apply; assess thresholds and classification separately.

Ensure the report/block controls in the product are staffed and operational, preserve only the information needed for safety/legal response, and have a documented abuse escalation process. Avoid promising automatic content checking in the Terms unless the feature is actually operating and its scope is accurately described.

### CERT-In and incident readiness

CERT-In’s directions under section 70B of the IT Act require covered entities to report specified cyber incidents within six hours of noticing them or being informed of them, and to maintain ICT-system logs securely for a rolling 180 days within India. Counsel should confirm applicability and the current directions. Assign an incident owner and 24/7 escalation path, maintain compliant system logs without turning them into unnecessary chat-content retention, preserve evidence, and rehearse a six-hour reporting workflow.

The short chat-transcript retention period and longer security-log retention can coexist: keep the minimum event/security metadata needed for compliance, segregate it from message content, and apply separate retention and access controls.

### Terms and Privacy Policy review

Both current pages are explicitly marked “Draft for review before public launch”: [`app/templates/privacy.html`](./app/templates/privacy.html) and [`app/templates/terms.html`](./app/templates/terms.html). Do not treat these drafts as production-ready legal documents.

Before launch, have Indian counsel review and finalize them. In particular:

- Add the legal entity/operator identity and usable privacy and grievance contacts.
- State the purposes and data categories clearly, identify processors/recipients and relevant transfer arrangements, and explain user rights and how to exercise them.
- Make retention periods precise for account data, chat, moderation/audit records, and backups; align the promises with the actual deletion jobs.
- Explain security incident contact/escalation and the limits of chat privacy in plain language.
- Confirm the adult-only eligibility and reporting language against real signup enforcement and operating procedures.
- Ensure the Terms’ description of automated message checks, reporting, blocking, and account restrictions matches shipped behavior.
- Version policies and keep evidence of the exact notice/terms accepted at signup. The project notes indicate acceptance version and timestamp are stored; verify the user can separately understand privacy choices and withdraw optional sharing/consent where applicable.

If Talkative charges users or otherwise falls within the Consumer Protection Act, 2019 and Consumer Protection (E-Commerce) Rules, 2020, assess applicable disclosures, grievance, refund, and unfair-contract requirements before enabling payments or paid features.

## Google AdSense readiness

AdSense is a planned feature, not part of the reviewed implementation. Its planned use changes the privacy, content-policy, and ad-placement checks required before launch.

- **Do not place AdSense ads in the live chat or other private-communication screens.** Google’s publisher policies prohibit ads on pages where private communication is the primary focus. This appears to describe Talkative’s chat interface. Consider ads only on eligible, public, content-focused pages, and do not assume approval: Google also requires original, useful content and compliance with its current program and publisher policies.
- **Update the Privacy Policy before loading ad code.** Disclose that Google and other third-party vendors may use cookies or similar technologies to serve ads, including personalized ads based on prior visits; describe relevant data use/sharing and how users can manage ad personalization. Name or link to the relevant Google privacy/ad settings and vendor disclosures required by the current AdSense terms. Keep this accurate to the actual ad configuration.
- **Treat advertising as a separate purpose.** Do not pass chat contents, report contents, private profile fields, or account identifiers to ad scripts or use them to target ads. Load only the approved Google code on pages where ads are permitted, and review third-party requests and browser storage with network inspection.
- **Consent depends on user location and implementation.** For users in the EEA, UK, and Switzerland, Google requires disclosures and consent for cookies/local storage and personalized-ad data use. Check the current Google publisher requirement for a certified CMP integrated with the IAB TCF before serving there. If Talkative serves only India, confirm Indian privacy/consent requirements for the planned cookies, identifiers, and ad processing with counsel; do not represent Google’s EEA/UK/Swiss requirement as a blanket India-only CMP mandate. If serving other regions, assess their rules too.
- **Provide clear ad labeling and separation.** Ads must not be made to look like chat controls, navigation, or content; do not encourage clicks, put ads next to buttons likely to cause accidental clicks, or deploy overlays that obstruct conversations. Exclude ads from the generated chat-share image.
- **Meet operational AdSense requirements.** Complete Google’s site review and publisher verification, keep the site’s content and traffic sources compliant, publish and maintain `ads.txt` as instructed by AdSense, and monitor policy notifications and invalid traffic. Never click your own ads or incentivize users to click/view them.
- **Review user-generated content and moderation exposure.** Publishers are responsible for ad placement and site content. Keep ads away from any page that may contain prohibited, harmful, or user-generated content unless the current Google policies explicitly permit the placement and effective controls are in place.

## Planned product requirements (not yet implemented)

These are launch requirements recorded from product decisions. Completion status is noted per item.

### Signup verification
- Passwords require 12-256 printable non-space characters with lowercase, uppercase, number, and symbol. Punctuation is not stripped or blocked as “SQL-dangerous”; passwords are hashed and SQL is parameterized.
- Verify email ownership by sending an OTP before account creation completes. Enforce one account per email with the existing case-insensitive unique email constraint.
- Signup UI is a three-step flow: personal details, email OTP verification, then username selection and account creation.
- Phone number is no longer collected or used for signup; this is a product choice, not a general legal requirement.
- Startup migration clears and removes the phone column from the active user database. Legacy source databases and old backups are not modified; handle them under the retention/deletion process.
- OTP limits: cap sends per email/IP and per time window, short expiry, limited verification attempts per code, and resend cooldown. Do not reveal whether an email is already registered.
- OTP verification is wired for signup and login, including admin-provisioned accounts, using fixed code `123456` in development only. Production (`APP_ENV=production`) fails closed until real email delivery is implemented. Failed-code limits are active; the separate wrong-password limit remains outstanding.
- Wrong-password limits: throttle failed logins per account and per IP, with progressive delay or temporary lockout and audit events. The same applies to admin login.

### Message rules and sanitization
- **Done:** maximum message length is 128 characters, enforced server-side and by the chat input. Other sanitization requirements below remain open.
- Chosen behavior: **block the message and tell the sender the reason**; nothing is delivered to the peer and the draft is kept for editing.
- Block personal information: emails, phone numbers (including spaced/spelled/obfuscated forms), street-address patterns, URLs (with or without scheme, `www.`, shortened, "[dot]" forms), and off-platform handles.
- Block abusive and threatening language, terrorism/violent-extremism content, and exploit/malware payloads. Normalize first (Unicode NFKC, case, zero-width characters, repeated letters, leetspeak). Use a maintained multilingual list including Indian languages and transliterated text, with a false-positive review path.
- Current gap: `message_flags` (`talkative_backend/core/functions.py`) matches about 7 words and `http://`/`https://` only, so it misses most of the above and is easy to evade.
- Injection safety: do not rely on stripping symbols; it harms normal speech and does not stop injection. Use parameterized SQL everywhere, render messages with `textContent` (never `innerHTML`), a strict Content-Security-Policy, rejection of control characters/null bytes, and length limits. A full SQL-injection audit has not been performed; reviewed database code appeared parameterized.
- Apply the same rules to bio, profession, education, location, username, and report text.
- Test with evasion cases and false positives (for example "I live in Chennai" must not be blocked).
- Update the Terms wording about automated checks to match shipped behavior. Blocking reduces but cannot eliminate off-platform contact sharing.

### Conversation records, IP addresses, and activity history
- Conversation ID: **yes, one is already generated.** `match_or_queue` in `talkative_backend/planes/sqlite_chat_store.py` creates `"dm" + uuid4().hex` when two users are matched, and `/api/match` returns it as `conversation_id`. It is also the key in the admin database.
- Capture both participants' IP addresses at match time and store them with the conversation record. IPs are personal data: put them in the privacy notice, restrict admin access, set an explicit retention period, and trust only the real client IP from the TLS proxy (configure forwarded headers carefully, otherwise IPs can be spoofed). Retention must be reconciled with the current 24-hour admin archive and CERT-In log requirements.
- Record per-conversation user activity events: chat started, left chat, message blocked with category (explicit/abusive, personal information, URL shared, threat, exploit), report, block, and chat ended. Store the category rather than extra copies of content.
- Currently only coarse audit events exist (`chat_started`, `message_sent`, `message_blocked`, `user_reported`, `user_blocked`, `chat_ended`), without IP, without the blocked category, and `leave` is not audited separately.

### Inactive account deletion
- Accounts inactive for **1 year** must be processed for deletion. DPDP requires erasing personal data once the purpose is no longer served, and the privacy policy should state this period; confirm exact wording and any notice duties with counsel.
- Define "inactive" precisely: no successful login or presence ping for 365 days (the schema has `last_active_date` for streaks; confirm it tracks logins and not only chat). Do not count marketing emails as activity.
- Send warning notices (for example 30 and 7 days before) to the verified email, with a one-click way to keep the account, then delete automatically through a scheduled job.
- Deletion must cover the user database row, blocks, SQLite state keys, and any admin-archive or audit records tied to the user, within the stated retention limits, and backups on their normal expiry cycle. Record a deletion audit event without personal data, and free the phone-number slot.
- Existing `delete_user` in `user_store.py` removes only the user and block rows, so a full-erasure routine is needed. Test the job on a staging copy first and make it idempotent with a dry-run mode.
- Update the Privacy Policy and Terms (currently silent on inactivity) and the data-retention schedule.

### Logging and observability
- Add structured (JSON) application logging with a request/correlation ID on every request, user ID and conversation ID where applicable, event name, outcome, and latency. Never log passwords, OTPs, session secrets, full message text, or full phone numbers/emails.
- Log levels and rotation, shipped to central storage with alerts on error spikes, login/OTP abuse, SQLite failures, and unhandled exceptions.
- Add health/readiness endpoints, error tracking, and metrics. Gunicorn access and error logs should be captured from the container.
- Logs are personal data too: set retention, access controls, and keep security logs separate from chat content. CERT-In requires 180 days of ICT-system logs within India for covered entities; confirm applicability.

### Help and Support
- Add a "Help and Support" link in the shared footer beside Terms and Conditions and Privacy Policy (`app/templates/_footer.html`), with a page covering contact details, how to report/block, grievance officer contact and response times, account deletion, and security/abuse reporting. This also supports the IT Rules grievance requirement.

## How report and block work today
- **Report** (`/api/report`): requires an active chat. It lowers the reported peer's quality score by 8, increments their `reports_received` counter, and writes a `user_reported` audit event. It does **not** end the chat, record a reason or evidence, notify moderators, or limit repeat reports, so report abuse and duplicate reports are not controlled.
- **Block** (`/api/block`): requires an active chat. It stores a pair in the `blocks` table (permanent), writes `user_blocked`, ends the chat immediately without the 5-second leave delay, archives the transcript to the admin database, and removes the user from the queue. The matcher skips blocked pairs in either direction. There is no unblock option.
- Gaps to close: no report reason or category, no moderator review queue, no automatic action on repeated reports, no confirmation to the reporter, and no rate limit.

## Production release checklist

### Block public launch until

- [ ] TLS is enforced end to end; port 8000 is not public; Secure cookies, CSRF protection, and proxy trust are correctly configured.
- [ ] Login/signup/admin rate limiting and abuse controls are implemented and tested.
- [ ] Admin credentials are unique and rotated; admin access is restricted and reviewed.
- [ ] Real email OTP delivery before account creation and login, one account per email, and OTP/wrong-password limits are implemented and tested. Development OTP and unique-email enforcement are implemented; production authentication stays disabled until delivery exists.
- [ ] The 1-year inactive-account deletion job, with advance notice, is implemented and tested.
- [ ] Messages are limited to 128 characters and sanitized server-side as described above; structured logging and Help and Support are live.
- [ ] The 18+ restriction is technically enforced and report/block/escalation workflows are operational.
- [ ] Privacy and Terms drafts are reviewed by India-qualified counsel, finalized, and match actual product behavior.
- [ ] Before enabling AdSense, ads are excluded from chat/private-communication screens, the Privacy Policy and any required consent flow reflect the actual ad configuration, and Google has approved the site.
- [ ] Data inventory, retention schedule, processor list, rights/grievance process, incident response, and deletion verification are owned by named people.
- [ ] Encrypted backups and restore tests cover user DB, admin DB, and state DB; access is least-privilege.

### Before production rollout

- [ ] Confirm the supported deployment topology, migration procedure, rollback plan, and whether SQLite is suitable for expected concurrent users and recovery objectives.
- [ ] Pin/scan container images and dependencies; run the container as a non-root user; restrict container capabilities, filesystem writes, resource use, and network access.
- [ ] Add health checks, restart policies, monitoring/alerting, centralized security logs, time synchronization, and an incident runbook.
- [ ] Test signup/login abuse, CSRF, session expiry/logout, authorization boundaries, account deletion, report/block, backup restore, migration, and data expiry.
- [ ] Use separate staging/production secrets; ensure `.env` is never published; rotate credentials after any exposure.
- [ ] Confirm end-user support, grievance monitoring, moderation coverage, and operational ownership for required legal/incident deadlines.

## References

- [Digital Personal Data Protection framework — MeitY](https://www.meity.gov.in/data-protection-framework)
- [Information Technology (Intermediary Guidelines and Digital Media Ethics Code) Rules — MeitY](https://www.meity.gov.in/static/uploads/2026/02/550681ab908f8afb135b0ad42816a1c9.pdf)
- [CERT-In Directions under section 70B, dated April 28, 2022](https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf)
- [Google AdSense Program policies](https://support.google.com/adsense/answer/48182?hl=en)
- [Google AdSense eligibility requirements](https://support.google.com/adsense/answer/9724?hl=en)
- [Google AdSense EU user consent policy](https://support.google.com/adsense/answer/7670013?hl=en)
- [Google AdSense privacy policy and third-party vendor disclosures](https://support.google.com/adsense/answer/1348695?hl=en)
- [How AdSense uses cookies and publisher privacy disclosures](https://support.google.com/adsense/answer/7549925?hl=en)
- [Talkative architecture and known risks](./LOCAL_KB.md)
