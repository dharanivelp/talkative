function visibleShareMessages() {
    const container = document.getElementById("msgs");
    if (!container) return [];
    const bounds = container.getBoundingClientRect();
    const viewportTop = bounds.top + container.clientTop;
    const viewportBottom = viewportTop + container.clientHeight;
    return Array.from(container.children).filter((bubble) => {
        if (!bubble.matches(".msg, .mine")) return false;
        const rect = bubble.getBoundingClientRect();
        return rect.bottom > viewportTop && rect.top < viewportBottom;
    });
}

function updateShareButton() {
    const button = document.getElementById("shareChatButton");
    if (!button) return;
    button.disabled = visibleShareMessages().length === 0;
}

function wrapShareText(context, text, maxWidth) {
    const lines = [];
    for (const paragraph of String(text).split(/\r?\n/)) {
        let line = "";
        for (const word of paragraph.split(/\s+/).filter(Boolean)) {
            let part = "";
            for (const character of word) {
                if (part && context.measureText(part + character).width > maxWidth) {
                    if (line) lines.push(line);
                    lines.push(part);
                    line = "";
                    part = character;
                } else {
                    part += character;
                }
            }
            const candidate = line ? line + " " + part : part;
            if (line && context.measureText(candidate).width > maxWidth) {
                lines.push(line);
                line = part;
            } else {
                line = candidate;
            }
        }
        if (line) lines.push(line);
        else if (!paragraph) lines.push("");
    }
    return lines.length ? lines : [""];
}

function drawShareRoundRect(context, x, y, width, height, radius) {
    context.beginPath();
    context.moveTo(x + radius, y);
    context.lineTo(x + width - radius, y);
    context.arcTo(x + width, y, x + width, y + radius, radius);
    context.lineTo(x + width, y + height - radius);
    context.arcTo(x + width, y + height, x + width - radius, y + height, radius);
    context.lineTo(x + radius, y + height);
    context.arcTo(x, y + height, x, y + height - radius, radius);
    context.lineTo(x, y + radius);
    context.arcTo(x, y, x + radius, y, radius);
    context.closePath();
}

function loadShareLogo(dark) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error("Unable to load the Talkative logo."));
        image.src = dark
            ? "/static/logo/Talkative_Banner_White_on_Transparent_2400x720.png"
            : "/static/logo/Talkative_Banner_Black_on_Transparent_2400x720.png";
    });
}

function loadShareImage(source) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error("Unable to load a conversation badge icon."));
        image.src = source;
    });
}

async function loadShareSvg(svg) {
    const copy = svg.cloneNode(true);
    const style = getComputedStyle(svg);
    for (const property of ["color", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"]) {
        copy.style.setProperty(property, style.getPropertyValue(property));
    }
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml" }));
    try {
        return await loadShareImage(url);
    } finally {
        URL.revokeObjectURL(url);
    }
}

async function createConversationImage() {
    const bubbles = visibleShareMessages();
    if (!bubbles.length) throw new Error("Scroll to the messages you want to share.");

    const width = 1000;
    const padding = 44;
    const messageWidth = width - padding * 2;
    const maxBubbleWidth = Math.floor(messageWidth * 0.84);
    const measureCanvas = document.createElement("canvas");
    const measure = measureCanvas.getContext("2d");
    measure.font = "30px system-ui, sans-serif";
    const messages = bubbles.map((bubble) => {
        const text = bubble.textContent.trim();
        const lines = wrapShareText(measure, text, maxBubbleWidth - 48);
        const widestLine = Math.max(...lines.map((line) => measure.measureText(line).width));
        const bubbleWidth = Math.min(maxBubbleWidth, Math.max(180, widestLine + 48));
        return {
            lines,
            width: bubbleWidth,
            height: lines.length * 42 + 42,
            mine: bubble.classList.contains("mine"),
        };
    });

    const peerName = document.getElementById("peerName").textContent.trim() || "Conversation";
    const genderIcon = document.getElementById("peerGender");
    const age = document.getElementById("peerAge").textContent.trim();
    const country = document.getElementById("peerCountryName")?.textContent.trim();
    const countryFlag = document.getElementById("peerCountryFlag")?.textContent.trim();
    const scoreElement = document.getElementById("peerScore");
    const score = scoreElement.textContent.trim();
    const scoreBand = scoreElement.dataset.band;
    const streak = document.getElementById("peerStreakDays").textContent.trim();
    const scoreIcon = document.querySelector("#peerScoreStreakBadge .score-icon");
    const streakIcon = document.querySelector("#peerScoreStreakBadge .streak-value svg");
    const genderImagePromise = genderIcon.dataset.gender === "male" || genderIcon.dataset.gender === "female"
        ? loadShareImage("/static/icons/" + genderIcon.dataset.gender + ".svg")
        : loadShareSvg(genderIcon.querySelector('[data-gender-icon="neutral"]'));
    const [genderImage, scoreImage, streakImage] = await Promise.all([
        genderImagePromise,
        loadShareSvg(scoreIcon),
        loadShareSvg(streakIcon),
    ]);

    const countryLabel = country ? [countryFlag, country].filter(Boolean).join(" ") : "";
    measure.font = "18px system-ui, sans-serif";
    const ageWidth = measure.measureText(age).width;
    const flagWidth = measure.measureText(countryFlag || "").width;
    const countryWidth = measure.measureText(country || "").width;
    const identityBadgeWidth = 10 + 32 + (age ? 10 + ageWidth : 0)
        + (countryLabel ? 10 + 1 + 10 + flagWidth + 6 + countryWidth : 0) + 10;
    measure.font = "16px system-ui, sans-serif";
    const scoreWidth = measure.measureText(score).width;
    const streakWidth = measure.measureText(streak).width;
    const scoreBadgeWidth = 10 + 20 + 5 + scoreWidth + 8 + 1 + 8 + 20 + 5 + streakWidth + 10;
    measure.font = "700 32px system-ui, sans-serif";
    const nameNaturalWidth = measure.measureText(peerName).width;
    const nameLeft = padding + 250;
    const nameMaxWidth = Math.max(90, messageWidth - 250 - identityBadgeWidth - scoreBadgeWidth - 36);
    const nameFontSize = Math.min(32, Math.max(22, 32 * nameMaxWidth / Math.max(nameNaturalWidth, 1)));
    measure.font = "700 " + nameFontSize + "px system-ui, sans-serif";
    const nameWidth = measure.measureText(peerName).width;
    const identityBadgeX = nameLeft + nameWidth + 12;
    const badgeItems = [
        { type: "identity", width: identityBadgeWidth, x: identityBadgeX },
        { type: "score", width: scoreBadgeWidth, x: identityBadgeX + identityBadgeWidth + 8 },
    ];

    measure.font = "18px system-ui, sans-serif";
    const informationLines = Array.from(document.querySelectorAll("#peerProfileDetails > p"))
        .flatMap((detail) => {
            const label = detail.dataset.shareLabel;
            const text = detail.textContent.trim();
            return wrapShareText(measure, label ? label + ": " + text : text, messageWidth);
        });
    const informationTop = 124;
    const headerHeight = Math.max(112, informationTop + informationLines.length * 25 + 12);
    const messageTop = headerHeight + 20;
    const messageGap = 12;
    const messageHeight = messages.reduce((total, message) => total + message.height, 0)
        + Math.max(0, messages.length - 1) * messageGap;
    const height = Math.max(440, messageTop + messageHeight + 52);
    if (height > 30000) throw new Error("This conversation is too long to share as one image.");

    const canvas = document.createElement("canvas");
    const scale = 2;
    canvas.width = width * scale;
    canvas.height = width * scale;
    const context = canvas.getContext("2d");

    const dark = document.documentElement.dataset.theme === "dark";
    const colors = dark
        ? { background: "#080808", panel: "#111111", text: "#eeeeee", muted: "#aaaaaa", peer: "#242424", mine: "#303030" }
        : { background: "#f4f6f8", panel: "#ffffff", text: "#17202a", muted: "#59645f", peer: "#e9eef2", mine: "#d9f3e8" };
    context.fillStyle = colors.background;
    context.fillRect(0, 0, canvas.width, canvas.height);
    const contentScale = Math.min(1, width / height);
    context.scale(scale * contentScale, scale * contentScale);

    const logo = await loadShareLogo(dark);
    context.fillStyle = colors.panel;
    context.fillRect(0, 0, width, headerHeight);
    const logoWidth = 240;
    const logoHeight = 72;
    context.drawImage(logo, padding, (headerHeight - logoHeight) / 2, logoWidth, logoHeight);

    context.fillStyle = colors.text;
    context.font = "700 " + nameFontSize + "px system-ui, sans-serif";
    context.textBaseline = "middle";
    context.fillText(peerName, nameLeft, 56, nameMaxWidth);

    let detailY = 32;
    for (const badge of badgeItems) {
            const badgeX = badge.x;
            if (badge.type === "identity") {
                drawShareRoundRect(context, badgeX, detailY, badge.width, 48, 24);
                context.fillStyle = dark ? "#292929" : "#e4ede9";
                context.fill();
                context.drawImage(genderImage, badgeX + 9, detailY + 8, 32, 32);
                context.fillStyle = dark ? "#dddddd" : "#205b50";
                context.font = "650 18px system-ui, sans-serif";
                context.textBaseline = "middle";
                measure.font = "18px system-ui, sans-serif";
                let itemX = badgeX + 51;
                if (age) {
                    context.fillText(age, itemX, detailY + 24, 150);
                    itemX += measure.measureText(age).width + 10;
                }
                if (countryLabel) {
                    context.fillStyle = dark ? "#dddddd66" : "#205b5066";
                    context.fillRect(itemX, detailY + 10, 1, 28);
                    itemX += 10;
                    context.fillStyle = dark ? "#dddddd" : "#205b50";
                    context.font = "19px system-ui, sans-serif";
                    context.fillText(countryFlag || "", itemX, detailY + 24);
                    itemX += measure.measureText(countryFlag || "").width + 6;
                    context.font = "500 18px system-ui, sans-serif";
                    context.fillText(country, itemX, detailY + 24, 150);
                }
            } else {
                drawShareRoundRect(context, badgeX, detailY, badge.width, 44, 22);
                context.fillStyle = dark ? "#1d2923" : "#f3f8f5";
                context.fill();
                context.strokeStyle = dark ? "#444444" : "#c8d4ce";
                context.lineWidth = 1;
                context.stroke();
                context.drawImage(scoreImage, badgeX + 10, detailY + 12, 20, 20);
                context.font = "700 16px system-ui, sans-serif";
                context.fillStyle = { low: "#bd4b46", mid: "#ad751b", high: "#21845c" }[scoreBand] || (dark ? "#dddddd" : "#205b50");
                context.fillText(score, badgeX + 35, detailY + 22, 48);
                measure.font = "16px system-ui, sans-serif";
                const dividerX = badgeX + 43 + measure.measureText(score).width;
                context.fillStyle = dark ? "#dddddd40" : "#205b5040";
                context.fillRect(dividerX, detailY + 10, 1, 24);
                context.drawImage(streakImage, dividerX + 9, detailY + 12, 20, 20);
                context.fillStyle = dark ? "#dddddd" : "#205b50";
                context.fillText(streak, dividerX + 34, detailY + 22, 48);
            }
    }

    context.fillStyle = colors.muted;
    context.font = "18px system-ui, sans-serif";
    context.textBaseline = "alphabetic";
    detailY = informationTop + 18;
    for (const line of informationLines) {
        context.fillText(line, padding, detailY, messageWidth);
        detailY += 25;
    }

    const positions = [];
    let y = messageTop;
    for (const message of messages) {
        const x = message.mine ? width - padding - message.width : padding;
        positions.push({ ...message, x, y });
        y += message.height + messageGap;
    }

    context.save();
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.globalAlpha = 0.075;
    const watermarkWidth = 1000;
    const watermarkHeight = watermarkWidth * 0.3;
    const chatTop = messageTop * scale * contentScale;
    const chatHeight = canvas.height - chatTop;
    context.drawImage(logo, (canvas.width - watermarkWidth) / 2, chatTop + (chatHeight - watermarkHeight) / 2, watermarkWidth, watermarkHeight);
    context.restore();

    context.font = "30px system-ui, sans-serif";
    context.textBaseline = "top";
    for (const message of positions) {
        drawShareRoundRect(context, message.x, message.y, message.width, message.height, 14);
        context.fillStyle = message.mine ? colors.mine : colors.peer;
        context.fill();
        context.fillStyle = colors.text;
        message.lines.forEach((line, index) => {
            context.fillText(line, message.x + 24, message.y + 21 + index * 42, message.width - 48);
        });
    }

    return new Promise((resolve, reject) => {
        canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Unable to create the conversation image.")), "image/png");
    });
}

async function shareChatSnapshot() {
    const button = document.getElementById("shareChatButton");
    const status = document.getElementById("shareStatus");
    button.disabled = true;
    try {
        const blob = await createConversationImage();
        const filename = "talkative-conversation-" + new Date().toISOString().slice(0, 10) + ".png";
        if (typeof File === "function" && navigator.share && navigator.canShare) {
            const file = new File([blob], filename, { type: "image/png" });
            if (navigator.canShare({ files: [file] })) {
                await navigator.share({ title: "Talkative conversation", files: [file] });
                return;
            }
        }
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (error) {
        if (error.name !== "AbortError") status.textContent = error.message || "Unable to share this conversation.";
    } finally {
        updateShareButton();
    }
}

function initializeShareButton() {
    const actions = document.querySelector(".chat-actions");
    const endButton = document.getElementById("nextChatButton");
    if (!actions || !endButton || document.getElementById("shareChatButton")) return;
    const button = document.createElement("button");
    button.id = "shareChatButton";
    button.type = "button";
    button.className = "share-chat-button";
    button.title = "Capture conversation image";
    button.setAttribute("aria-label", "Capture conversation image");
    button.disabled = true;
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h3l2-3h6l2 3h3v13H4z"></path><circle cx="12" cy="13" r="4"></circle></svg>';
    button.addEventListener("click", shareChatSnapshot);
    endButton.before(button);

    const status = document.createElement("p");
    status.id = "shareStatus";
    status.className = "share-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    actions.closest(".top").insertAdjacentElement("afterend", status);

    const messages = document.getElementById("msgs");
    messages.addEventListener("scroll", updateShareButton, { passive: true });
    new MutationObserver(updateShareButton).observe(messages, { childList: true });
    updateShareButton();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeShareButton, { once: true });
} else {
    initializeShareButton();
}