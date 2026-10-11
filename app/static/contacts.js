(() => {
    let currentContact = null;
    let returnToRandomChat = false;
    let lastContactMessageId = 0;
    let contactPollTimer = null;
    let contactPollInProgress = false;
    let typingSendTimer = null;
    let lastTypingSentAt = 0;
    let firstContactMessageLoad = true;
    let contactListTimer = null;
    let contactListLoaded = false;
    const latestMessageIds = new Map();
    const unreadCounts = new Map();
    let messageSoundPreference = (() => {
        try {
            return localStorage.getItem("talkative-contact-sounds") !== "false";
        } catch (error) {
            console.warn("Contact sound preference could not be loaded", error);
            return true;
        }
    })();

    async function contactApi(url, options = {}) {
        const response = await fetch(url, {
            credentials: "same-origin",
            ...options,
            headers: {
                "Content-Type": "application/json",
                ...(options.headers || {}),
            },
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Request failed");
        return data;
    }

    function appendPeerDetails(container, peer) {
        if (!peer) return;
        const details = document.createElement("div");
        details.className = "contact-peer-summary";

        const badges = document.createElement("div");
        badges.className = "contact-peer-badges peer-badges";
        const ageBadge = document.createElement("span");
        ageBadge.className = "age-badge";
        const genderIcon = document.createElement("span");
        genderIcon.className = "gender-icon";
        const gender = ["male", "female"].includes(peer.gender) ? peer.gender : "neutral";
        genderIcon.dataset.gender = gender;
        if (gender === "neutral") genderIcon.setAttribute("data-gender-icon", "neutral");
        genderIcon.setAttribute("role", "img");
        genderIcon.setAttribute("aria-label", peer.gender === "male" ? "Male" : peer.gender === "female" ? "Female" : "Gender not specified");
        const neutralIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        neutralIcon.setAttribute("viewBox", "0 0 24 24");
        neutralIcon.setAttribute("aria-hidden", "true");
        neutralIcon.innerHTML = '<circle cx="12" cy="8" r="4"></circle><path d="M4 21a8 8 0 0 1 16 0"></path>';
        genderIcon.append(neutralIcon);
        const age = document.createElement("span");
        age.textContent = peer.age_category || "";
        ageBadge.append(genderIcon, age);
        badges.append(ageBadge);

        if (peer.country_name) {
            const country = document.createElement("span");
            country.className = "peer-country";
            country.title = peer.country_name;
            const flag = document.createElement("span");
            flag.className = "peer-country-flag";
            flag.setAttribute("aria-hidden", "true");
            flag.textContent = countryFlag(peer.country_code);
            const countryName = document.createElement("span");
            countryName.textContent = peer.country_name;
            country.append(flag, countryName);
            badges.append(country);
        }

        const scoreStreak = document.createElement("div");
        scoreStreak.className = "score-streak-badge contact-score-streak";
        scoreStreak.setAttribute("role", "group");
        const scoreValue = document.createElement("span");
        scoreValue.className = "score-streak-value";
        const scoreIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        scoreIcon.setAttribute("viewBox", "0 0 24 24");
        scoreIcon.setAttribute("aria-hidden", "true");
        scoreIcon.innerHTML = '<path d="m12 3 2.6 5.2 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8L12 3Z"></path>';
        const scoreText = document.createElement("strong");
        const scoreNumber = Math.max(0, Math.min(100, Number(peer.score) || 0));
        scoreText.textContent = String(scoreNumber);
        scoreText.dataset.band = scoreNumber < 40 ? "low" : scoreNumber < 70 ? "mid" : "high";
        scoreText.setAttribute("aria-label", `Convo score ${scoreNumber}`);
        scoreValue.append(scoreIcon, scoreText);
        const divider = document.createElement("span");
        divider.className = "score-streak-divider";
        divider.setAttribute("aria-hidden", "true");
        const streakValue = document.createElement("span");
        streakValue.className = "score-streak-value streak-value";
        const streakIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        streakIcon.setAttribute("viewBox", "0 0 24 24");
        streakIcon.setAttribute("aria-hidden", "true");
        streakIcon.innerHTML = '<path d="M12 22c4.2 0 7-2.8 7-6.7 0-2.8-1.6-4.7-3.5-6.6-.1 1.8-.8 2.8-1.9 3.5C14 8.1 12.1 4.8 9 2 9.6 6.8 5 8.7 5 14.5 5 19 7.8 22 12 22Z"></path><path d="M12 19c1.5 0 2.5-1.1 2.5-2.6 0-1-.5-1.8-1.4-2.7-.1 1.1-.6 1.5-1.1 1.8-.1-.9-.6-1.7-1.4-2.4-.2 1.8-1.1 2.5-1.1 3.5C9.5 18 10.5 19 12 19Z"></path>';
        const streakText = document.createElement("strong");
        const streakDays = Math.max(0, Number(peer.streak_days) || 0);
        streakText.textContent = String(streakDays);
        streakText.setAttribute("aria-label", `${streakDays} day streak`);
        streakValue.append(streakIcon, streakText);
        scoreStreak.append(scoreValue, divider, streakValue);
        scoreStreak.setAttribute("aria-label", `Convo score ${scoreNumber}, streak ${streakDays} days`);
        badges.append(scoreStreak);
        details.append(badges);

        const profileLines = [];
        for (const label of ["bio", "profession", "education", "location"]) {
            const value = peer[label];
            if (typeof value !== "string" || !value.trim()) continue;
            const line = document.createElement("span");
            line.className = `contact-profile-${label}`;
            if (label !== "bio") line.append(document.createTextNode(`${label[0].toUpperCase()}${label.slice(1)}: `));
            line.append(document.createTextNode(value));
            profileLines.push(line);
        }
        if (profileLines.length) {
            const profile = document.createElement("div");
            profile.className = "contact-peer-profile";
            profile.append(...profileLines);
            details.append(profile);
        }
        container.append(details);
    }

    function countryFlag(code) {
        if (!/^[A-Z]{2}$/.test(code || "") || code === "ZZ") return "🌐";
        return [...code].map((letter) => String.fromCodePoint(letter.charCodeAt(0) + 127397)).join("");
    }

    function presenceLabel(presence = {}) {
        if (presence.online) return "Online";
        const lastSeen = Number(presence.last_seen);
        if (!Number.isFinite(lastSeen) || lastSeen <= 0) return "Offline";
        const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - lastSeen));
        if (elapsed < 60) return "Last seen just now";
        if (elapsed < 3600) return `Last seen ${Math.floor(elapsed / 60)}m ago`;
        if (elapsed < 86400) return `Last seen ${Math.floor(elapsed / 3600)}h ago`;
        const days = Math.floor(elapsed / 86400);
        return `Last seen ${days}d ago`;
    }

    function contactMessage(contact) {
        const row = document.createElement("li");
        row.className = "contact-message-row";
        const unreadCount = unreadCounts.get(contact.conversation_id);
        const name = contact.peer?.name || contact.name || "Participant";
        const open = document.createElement("button");
        open.type = "button";
        open.className = "contact-open-button";
        open.classList.toggle("has-unread", Boolean(unreadCount));
        open.dataset.conversationId = contact.conversation_id;
        const peerPresence = contact.peer || {};
        open.setAttribute(
            "aria-label",
            `Open chat with ${name}, ${presenceLabel(peerPresence)}${unreadCount ? `, ${unreadCount} unread messages` : ""}`,
        );

        const avatar = document.createElement("span");
        avatar.className = `contact-avatar${peerPresence.online ? " is-online" : ""}`;
        avatar.setAttribute("aria-hidden", "true");
        avatar.title = presenceLabel(peerPresence);
        avatar.textContent = name.trim().charAt(0).toLocaleUpperCase() || "?";
        let colorHash = 0;
        for (const character of name) colorHash = (colorHash * 31 + character.charCodeAt(0)) % 360;
        avatar.style.setProperty("--contact-avatar-hue", String(colorHash));

        const details = document.createElement("span");
        details.className = "contact-row-details";
        const heading = document.createElement("span");
        heading.className = "contact-row-heading";
        const nameLabel = document.createElement("strong");
        nameLabel.className = "contact-row-name";
        nameLabel.textContent = name;
        heading.append(nameLabel);
        if (contact.last_message_at) {
            const time = new Date(contact.last_message_at);
            if (!Number.isNaN(time.valueOf())) {
                const timestamp = document.createElement("time");
                timestamp.className = "contact-row-time";
                timestamp.dateTime = contact.last_message_at;
                timestamp.textContent = time.toLocaleTimeString([], {
                    hour: "numeric",
                    minute: "2-digit",
                });
                heading.append(timestamp);
            }
        }
        const preview = document.createElement("span");
        preview.className = "contact-message-preview";
        const messagePreview = contact.last_message
            ? `${contact.last_message_mine ? "You: " : ""}${contact.last_message}`
            : "Start a conversation";
        preview.textContent = messagePreview;
        details.append(heading, preview);

        if (unreadCount) {
            const badge = document.createElement("span");
            badge.className = "contact-unread-badge";
            badge.textContent = String(unreadCount);
            badge.setAttribute("aria-label", `${badge.textContent} unread messages`);
            details.append(badge);
        }

        open.append(avatar, details);
        open.addEventListener("click", () => window.openContactConversation(contact));
        row.append(open);
        return row;
    }

    function syncActiveContactUi() {
        document.querySelectorAll(".contact-find-card").forEach((button) => {
            const isActive = !currentContact;
            button.classList.toggle("is-active", isActive);
            if (isActive) button.setAttribute("aria-current", "true");
            else button.removeAttribute("aria-current");
        });
        document.querySelectorAll(".contact-open-button").forEach((button) => {
            const isActive = button.dataset.conversationId === currentContact?.conversation_id;
            button.classList.toggle("is-active", isActive);
            if (isActive) button.setAttribute("aria-current", "true");
            else button.removeAttribute("aria-current");
        });
        const matchWaiting = Boolean(window.isContactMatchWaiting?.());
        const matchPeer = window.getContactMatchPeer?.();
        const unreadContact = lastRenderedContacts.find((contact) => unreadCounts.has(contact.conversation_id));
        document.querySelectorAll(".contact-find-card").forEach((button) => {
            const subtitle = button.querySelector(".contact-find-subtitle");
            const indicator = button.querySelector(".contact-new-message-indicator");
            if (!subtitle || !indicator) return;
            if (matchWaiting) {
                subtitle.textContent = "Finding someone…";
                indicator.classList.add("hidden");
            } else if (matchPeer) {
                subtitle.textContent = matchPeer.name || "Someone is ready to chat";
                indicator.textContent = "New message";
                indicator.classList.remove("hidden");
            } else if (unreadContact) {
                subtitle.textContent = unreadContact.peer?.name || unreadContact.name || "A contact";
                indicator.textContent = "New message";
                indicator.classList.remove("hidden");
            } else {
                subtitle.textContent = "Start a new conversation";
                indicator.classList.add("hidden");
            }
        });
    }

    let lastRenderedContacts = [];

    function renderContactList(contacts, limit) {
        lastRenderedContacts = contacts;
        for (const listId of ["contactListHome", "contactListChat"]) {
            const list = document.getElementById(listId);
            list.replaceChildren();
            contacts.forEach((contact) => list.append(contactMessage(contact)));
            if (!contacts.length) {
                const empty = document.createElement("li");
                empty.className = "contact-empty";
                empty.textContent = "People you both choose to stay in touch with will appear here.";
                list.append(empty);
            }
        }
        for (const countId of ["contactCountHome", "contactCountChat"]) {
            document.getElementById(countId).textContent = `${contacts.length}/${limit}`;
        }
        syncActiveContactUi();
    }

    function notifyIncomingMessage(contact) {
        if (contact.conversation_id !== currentContact?.conversation_id) {
            unreadCounts.set(contact.conversation_id, (unreadCounts.get(contact.conversation_id) || 0) + 1);
        }
        if (messageSoundPreference && window.playMessageSound) window.playMessageSound();
        if (document.hidden && "Notification" in window && Notification.permission === "granted") {
            const notification = new Notification(`Message from ${contact.peer?.name || contact.name}`, {
                body: "Open Talkative to read your new message.",
                tag: `talkative-${contact.conversation_id}`,
            });
            notification.onclick = () => {
                window.focus();
                window.openContactConversation(contact);
                notification.close();
            };
        }
    }

    async function fetchAndRenderContacts(showStatus = true) {
        const status = document.getElementById("contactListStatusHome");
        if (showStatus) status.textContent = "Loading chats…";
        try {
            const result = await contactApi("/api/contacts");
            for (const contact of result.contacts) {
                const id = contact.conversation_id;
                const latestId = Number(contact.last_message_id) || 0;
                const previousId = latestMessageIds.get(id);
                if (contactListLoaded && previousId !== undefined && latestId > previousId
                    && !contact.last_message_mine
                    && contact.conversation_id !== currentContact?.conversation_id) {
                    notifyIncomingMessage(contact);
                }
                if (previousId === undefined || latestId > previousId) latestMessageIds.set(id, latestId);
                if (contact.last_message_mine) unreadCounts.delete(id);
            }
            renderContactList(result.contacts, result.limit);
            document.getElementById("contactListStatusHome").textContent = "";
            document.getElementById("contactListStatusChat").textContent = "";
            contactListLoaded = true;
            return result.contacts;
        } catch (error) {
            const message = showStatus
                ? error.message
                : `Unable to refresh Stayed in touch chats: ${error.message}`;
            status.textContent = message;
            document.getElementById("contactListStatusChat").textContent = message;
            return null;
        }
    }

    window.contactSoundsEnabled = messageSoundPreference;
    window.refreshContactSidebarStatus = syncActiveContactUi;

    window.loadContactList = async function loadContactList() {
        await fetchAndRenderContacts();
    };

    window.startContactNotifications = function startContactNotifications() {
        clearInterval(contactListTimer);
        fetchAndRenderContacts(false);
        contactListTimer = setInterval(() => fetchAndRenderContacts(false), 5000);
    };

    function addContactMessage(message) {
        const row = document.createElement("article");
        row.className = `contact-message-entry${message.mine ? " contact-message-outgoing" : ""}`;
        const bubble = document.createElement("div");
        bubble.className = "contact-message";
        const content = document.createElement("p");
        content.textContent = message.text;
        const time = document.createElement("time");
        time.className = "contact-message-time";
        time.dateTime = message.created_at;
        const date = new Date(message.created_at);
        time.textContent = Number.isNaN(date.valueOf())
            ? ""
            : date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        const meta = document.createElement("div");
        meta.className = "contact-message-meta";
        meta.append(time);
        bubble.append(content);
        row.append(bubble, meta);
        document.getElementById("contactMessages").append(row);
    }

    async function loadContactMessages() {
        if (!currentContact || contactPollInProgress) return;
        contactPollInProgress = true;
        const selected = currentContact;
        try {
            const after = firstContactMessageLoad ? "" : `?after=${lastContactMessageId}`;
            const result = await contactApi(
                `/api/contact-messages/${encodeURIComponent(selected.conversation_id)}${after}`,
            );
            if (currentContact !== selected) return;
            const isInitialLoad = firstContactMessageLoad;
            if (isInitialLoad) {
                document.getElementById("contactMessages").replaceChildren();
                firstContactMessageLoad = false;
            }
            for (const message of result.messages) {
                addContactMessage(message);
                lastContactMessageId = Math.max(lastContactMessageId, message.id);
                if (!message.mine && !isInitialLoad) {
                    if (selected.conversation_id !== currentContact.conversation_id || document.hidden) {
                        notifyIncomingMessage(selected);
                    } else if (messageSoundPreference && window.playMessageSound) {
                        window.playMessageSound();
                    }
                }
            }
            if (result.messages.length) {
                const list = document.getElementById("contactMessages");
                list.scrollTop = list.scrollHeight;
                latestMessageIds.set(selected.conversation_id, lastContactMessageId);
                unreadCounts.delete(selected.conversation_id);
                fetchAndRenderContacts(false);
            }
            document.getElementById("contactConversationStatus").textContent = "";
            document.getElementById("contactTypingIndicator").classList.toggle("hidden", !result.typing);
            updateContactPeerPresence(result.peer_presence || selected.peer || {});
            selected.peer = {
                ...(selected.peer || {}),
                ...(result.peer_presence || {}),
            };
        } catch (error) {
            if (currentContact === selected) {
                document.getElementById("contactConversationStatus").textContent = error.message;
            }
        } finally {
            contactPollInProgress = false;
        }
    }

    window.openContactConversation = async function openContactConversation(contact) {
        currentContact = contact;
        syncActiveContactUi();
        unreadCounts.delete(contact.conversation_id);
        returnToRandomChat = Boolean(window.hasActiveRandomChat && window.hasActiveRandomChat());
        lastContactMessageId = 0;
        firstContactMessageLoad = true;
        contactPollInProgress = false;
        clearInterval(contactPollTimer);
        document.getElementById("contactConversationName").textContent = contact.peer?.name || contact.name;
        updateContactPeerPresence(contact.peer || {});
        const peerInfo = document.getElementById("contactPeerInfo");
        peerInfo.replaceChildren();
        appendPeerDetails(peerInfo, contact.peer || { name: contact.name });
        document.getElementById("contactConversationStatus").textContent = "Loading messages…";
        document.getElementById("contactMessageInput").value = "";
        await fetchAndRenderContacts(false);
        if (window.show) window.show("chat");
        window.setMobileSection?.("chat");
        window.setMobileChatView?.("thread");
        document.getElementById("chat").classList.add("hidden");
        document.getElementById("contactConversation").classList.remove("hidden");
        await loadContactMessages();
        contactPollTimer = setInterval(loadContactMessages, 1800);
        document.getElementById("contactMessageInput").focus();
    };

    window.closeContactConversation = function closeContactConversation() {
        clearInterval(contactPollTimer);
        contactPollTimer = null;
        currentContact = null;
        syncActiveContactUi();
        document.getElementById("contactConversation").classList.add("hidden");
        if (returnToRandomChat) {
            if (window.restoreRandomChatView) window.restoreRandomChatView();
            else if (window.show) window.show("chat");
            window.setMobileChatView?.("random");
        } else if (window.showHome) {
            window.showHome();
            window.setMobileChatView?.("list");
        }
        returnToRandomChat = false;
        window.loadContactList();
    };

    window.hideContactConversation = function hideContactConversation() {
        clearInterval(contactPollTimer);
        contactPollTimer = null;
        currentContact = null;
        returnToRandomChat = false;
        document.getElementById("contactConversation").classList.add("hidden");
    };

    window.sendContactMessage = async function sendContactMessage(event) {
        event.preventDefault();
        if (!currentContact) return;
        const input = document.getElementById("contactMessageInput");
        const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
        const text = input.value.trim();
        if (!text) return;
        button.disabled = true;
        try {
            await contactApi(
                `/api/contact-messages/${encodeURIComponent(currentContact.conversation_id)}`,
                { method: "POST", body: JSON.stringify({ text }) },
            );
            input.value = "";
            await loadContactMessages();
            await fetchAndRenderContacts(false);
        } catch (error) {
            document.getElementById("contactConversationStatus").textContent = error.message;
        } finally {
            button.disabled = false;
            input.focus();
        }
    };

    function updateContactPeerPresence(presence) {
        const status = document.getElementById("contactPeerPresence");
        const label = presenceLabel(presence);
        status.classList.toggle("is-online", Boolean(presence.online));
        status.setAttribute("aria-label", label);
        status.title = label;
    }

    window.notifyContactTyping = function notifyContactTyping() {
        if (!currentContact || !document.getElementById("contactMessageInput").value.trim()) return;
        if (Date.now() - lastTypingSentAt < 1000) {
            clearTimeout(typingSendTimer);
            typingSendTimer = setTimeout(window.notifyContactTyping, 1000);
            return;
        }
        lastTypingSentAt = Date.now();
        contactApi(`/api/contact-typing/${encodeURIComponent(currentContact.conversation_id)}`, {
            method: "POST",
        }).catch((error) => {
            document.getElementById("contactConversationStatus").textContent = error.message;
        });
    };

    window.removeCurrentContact = async function removeCurrentContact() {
        if (!currentContact || !confirm(`Remove ${currentContact.peer?.name || currentContact.name} from your chats?`)) return;
        try {
            await contactApi(
                `/api/contacts/${encodeURIComponent(currentContact.conversation_id)}`,
                { method: "DELETE" },
            );
            window.closeContactConversation();
        } catch (error) {
            document.getElementById("contactConversationStatus").textContent = error.message;
        }
    };
})();
