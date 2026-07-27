/**
 * Studiekompas — embeddable chat widget
 *
 * Usage on the UNLP website:
 *   <script src="widget.js"></script>
 *   <studiekompas-widget api-url="https://studiekompas-production.up.railway.app"></studiekompas-widget>
 *
 * Talks to two backend endpoints:
 *   POST {api-url}/api/consent  { session_id }              -> { status }
 *   POST {api-url}/api/chat     { session_id, message }      -> { reply }
 *
 * The chat itself stays hidden behind a consent notice until the visitor
 * explicitly accepts — no message is sent, and no conversation row is
 * created, until that happens.
 */

(function () {
  const TEMPLATE = `
    <style>
      :host {
        --sk-bg: #FAF7F2;
        --sk-ink: #26241F;
        --sk-ink-soft: #6B6558;
        --sk-teal: #1F4B4C;
        --sk-teal-dark: #163737;
        --sk-gold: #C89B3C;
        --sk-border: #E4DFD5;
        --sk-bubble-user: #1F4B4C;
        --sk-bubble-bot: #F1ECE2;
        all: initial;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 999999;
      }

      * { box-sizing: border-box; }

      .launcher {
        width: 60px;
        height: 60px;
        border-radius: 50%;
        background: var(--sk-teal);
        border: none;
        cursor: pointer;
        box-shadow: 0 6px 20px rgba(31, 75, 76, 0.35);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: transform 0.25s ease, box-shadow 0.25s ease;
      }
      .launcher:hover {
        transform: scale(1.05);
        box-shadow: 0 8px 26px rgba(31, 75, 76, 0.45);
      }
      .launcher svg {
        width: 28px;
        height: 28px;
        transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
      }
      .launcher.open svg {
        transform: rotate(135deg);
      }

      .panel {
        position: absolute;
        bottom: 76px;
        right: 0;
        width: 380px;
        max-width: calc(100vw - 32px);
        height: 560px;
        max-height: calc(100vh - 140px);
        background: var(--sk-bg);
        border-radius: 18px;
        border: 1px solid var(--sk-border);
        box-shadow: 0 20px 60px rgba(38, 36, 31, 0.25);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        opacity: 0;
        transform: translateY(16px) scale(0.98);
        pointer-events: none;
        transition: opacity 0.22s ease, transform 0.22s ease;
      }
      .panel.open {
        opacity: 1;
        transform: translateY(0) scale(1);
        pointer-events: auto;
      }

      .header {
        background: var(--sk-teal);
        color: #FAF7F2;
        padding: 18px 20px;
        display: flex;
        align-items: center;
        gap: 12px;
      }
      .header .compass {
        width: 26px;
        height: 26px;
        flex-shrink: 0;
      }
      .header .titles {
        display: flex;
        flex-direction: column;
        line-height: 1.25;
      }
      .header .titles .name {
        font-family: 'Fraunces', Georgia, serif;
        font-size: 16px;
        font-weight: 600;
        letter-spacing: 0.2px;
      }
      .header .titles .sub {
        font-size: 11.5px;
        color: #CFE3E1;
        letter-spacing: 0.2px;
      }

      .disclosure {
        font-size: 11.5px;
        color: var(--sk-ink-soft);
        background: #F1ECE2;
        border-bottom: 1px solid var(--sk-border);
        padding: 8px 20px;
        line-height: 1.5;
      }

      .consent-gate {
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        flex: 1;
      }
      .consent-gate p {
        font-size: 13.5px;
        color: var(--sk-ink-soft);
        line-height: 1.6;
        margin: 0;
      }
      .consent-gate button {
        background: var(--sk-teal);
        color: #FAF7F2;
        border: none;
        border-radius: 10px;
        padding: 11px 16px;
        font-size: 14px;
        font-family: inherit;
        cursor: pointer;
        transition: background 0.2s ease;
      }
      .consent-gate button:hover {
        background: var(--sk-teal-dark);
      }

      .messages {
        flex: 1;
        overflow-y: auto;
        padding: 18px 16px;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .msg {
        max-width: 80%;
        padding: 10px 14px;
        border-radius: 14px;
        font-size: 14px;
        line-height: 1.5;
        white-space: pre-wrap;
      }
      .msg.bot {
        background: var(--sk-bubble-bot);
        color: var(--sk-ink);
        align-self: flex-start;
        border-bottom-left-radius: 4px;
      }
      .msg.user {
        background: var(--sk-bubble-user);
        color: #FAF7F2;
        align-self: flex-end;
        border-bottom-right-radius: 4px;
      }
      .msg.typing {
        display: flex;
        gap: 4px;
        align-items: center;
        padding: 12px 16px;
      }
      .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--sk-ink-soft);
        opacity: 0.5;
        animation: bounce 1.2s infinite ease-in-out;
      }
      .dot:nth-child(2) { animation-delay: 0.15s; }
      .dot:nth-child(3) { animation-delay: 0.3s; }
      @keyframes bounce {
        0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
        30% { transform: translateY(-4px); opacity: 1; }
      }

      .human-request {
        text-align: center;
        padding: 4px 0 2px;
      }
      .human-request button {
        background: none;
        border: none;
        color: var(--sk-teal);
        font-size: 12px;
        text-decoration: underline;
        cursor: pointer;
        font-family: inherit;
      }
      .human-request.hidden,
      .composer.hidden {
        display: none;
      }

      .composer {
        border-top: 1px solid var(--sk-border);
        padding: 12px;
        display: flex;
        gap: 8px;
        background: var(--sk-bg);
      }
      .composer textarea {
        flex: 1;
        resize: none;
        border: 1px solid var(--sk-border);
        border-radius: 10px;
        padding: 10px 12px;
        font-family: inherit;
        font-size: 14px;
        color: var(--sk-ink);
        background: #fff;
        max-height: 90px;
        line-height: 1.4;
      }
      .composer textarea:focus {
        outline: 2px solid var(--sk-gold);
        outline-offset: 1px;
      }
      .composer button.send {
        background: var(--sk-teal);
        border: none;
        color: #FAF7F2;
        border-radius: 10px;
        width: 42px;
        height: 42px;
        flex-shrink: 0;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s ease;
      }
      .composer button.send:hover { background: var(--sk-teal-dark); }
      .composer button.send:disabled {
        opacity: 0.5;
        cursor: default;
      }

      @media (prefers-reduced-motion: reduce) {
        .launcher svg, .panel, .dot { transition: none !important; animation: none !important; }
      }
    </style>

    <button class="launcher" aria-label="Open Studiekompas chat" aria-expanded="false">
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="12" r="9.25" stroke="#FAF7F2" stroke-width="1.4"/>
        <path d="M15.5 8.5L13 13L8.5 15.5L11 11L15.5 8.5Z" fill="#C89B3C" stroke="#C89B3C" stroke-linejoin="round"/>
      </svg>
    </button>

    <div class="panel" role="dialog" aria-label="Studiekompas chat">
      <div class="header">
        <svg class="compass" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="12" cy="12" r="9.25" stroke="#FAF7F2" stroke-width="1.2"/>
          <path d="M15.5 8.5L13 13L8.5 15.5L11 11L15.5 8.5Z" fill="#C89B3C" stroke="#C89B3C" stroke-linejoin="round"/>
        </svg>
        <div class="titles">
          <span class="name">UNLP Studiekompas</span>
          <span class="sub">Ontdek welke opleiding écht bij jou past</span>
        </div>
      </div>

      <div class="disclosure">
        Je chat hier met een AI-assistent, geen mens. Je kunt op elk moment vragen om verder te gaan met een opleidingsadviseur.
      </div>

      <div class="consent-gate" id="consent-gate">
        <p>
          Voordat we starten: dit gesprek wordt opgeslagen zodat een UNLP-opleidingsadviseur
          je goed kan helpen. We gebruiken je gegevens alleen hiervoor en bewaren ze niet
          langer dan nodig. Ga je hiermee akkoord?
        </p>
        <button id="consent-accept" type="button">Ja, ik ga akkoord</button>
      </div>

      <div class="messages" id="messages" style="display: none;"></div>

      <div class="human-request hidden">
        <button id="human-btn" type="button">Liever met een mens spreken?</button>
      </div>

      <div class="composer hidden">
        <textarea id="input" rows="1" placeholder="Typ je bericht..." aria-label="Je bericht"></textarea>
        <button class="send" id="send-btn" aria-label="Verstuur bericht">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M4 12L20 4L14 20L11 13L4 12Z" fill="#FAF7F2"/>
          </svg>
        </button>
      </div>
    </div>
  `;

  const WELCOME_MESSAGE =
    "Welkom bij het UNLP Studiekompas. Ik help je graag ontdekken welke opleiding het beste bij jou past. Mag ik eerst vragen wat jou vandaag naar onze website heeft gebracht?";

  class StudiekompasWidget extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = TEMPLATE;
      this.sessionId = crypto.randomUUID();
      this.isOpen = false;
      this.isSending = false;
      this.consentGiven = false;
    }

    connectedCallback() {
      this.apiUrl = (this.getAttribute("api-url") || "").replace(/\/$/, "");

      this.launcher = this.shadowRoot.querySelector(".launcher");
      this.panel = this.shadowRoot.querySelector(".panel");
      this.messagesEl = this.shadowRoot.querySelector("#messages");
      this.input = this.shadowRoot.querySelector("#input");
      this.sendBtn = this.shadowRoot.querySelector("#send-btn");
      this.humanBtn = this.shadowRoot.querySelector("#human-btn");
      this.consentGate = this.shadowRoot.querySelector("#consent-gate");
      this.consentAcceptBtn = this.shadowRoot.querySelector("#consent-accept");
      this.composerEl = this.shadowRoot.querySelector(".composer");
      this.humanRequestEl = this.shadowRoot.querySelector(".human-request");

      this.launcher.addEventListener("click", () => this.toggle());
      this.sendBtn.addEventListener("click", () => this.sendMessage());
      this.humanBtn.addEventListener("click", () => this.requestHuman());
      this.consentAcceptBtn.addEventListener("click", () => this.acceptConsent());
      this.input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          this.sendMessage();
        }
      });
      this.input.addEventListener("input", () => this.autoResize());
    }

    toggle() {
      this.isOpen = !this.isOpen;
      this.launcher.classList.toggle("open", this.isOpen);
      this.panel.classList.toggle("open", this.isOpen);
      this.launcher.setAttribute("aria-expanded", String(this.isOpen));

      if (this.isOpen && this.consentGiven) {
        this.input.focus();
      }
    }

    async acceptConsent() {
      this.consentGiven = true;
      this.consentGate.style.display = "none";
      this.messagesEl.style.display = "flex";
      this.composerEl.classList.remove("hidden");
      this.humanRequestEl.classList.remove("hidden");
      this.appendMessage("bot", WELCOME_MESSAGE);
      this.input.focus();

      try {
        await fetch(`${this.apiUrl}/api/consent`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: this.sessionId }),
        });
      } catch (err) {
        console.error("Studiekompas consent recording failed:", err);
      }
    }

    autoResize() {
      this.input.style.height = "auto";
      this.input.style.height = Math.min(this.input.scrollHeight, 90) + "px";
    }

    appendMessage(role, text) {
      const div = document.createElement("div");
      div.className = `msg ${role}`;
      div.textContent = text;
      this.messagesEl.appendChild(div);
      this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
      return div;
    }

    showTyping() {
      const div = document.createElement("div");
      div.className = "msg bot typing";
      div.innerHTML = `<span class="dot"></span><span class="dot"></span><span class="dot"></span>`;
      this.messagesEl.appendChild(div);
      this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
      return div;
    }

    async sendMessage(overrideText) {
      if (!this.consentGiven) return;

      const text = (overrideText ?? this.input.value).trim();
      if (!text || this.isSending) return;

      this.appendMessage("user", text);
      this.input.value = "";
      this.autoResize();
      this.isSending = true;
      this.sendBtn.disabled = true;

      const typingEl = this.showTyping();

      try {
        const res = await fetch(`${this.apiUrl}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: this.sessionId, message: text }),
        });

        if (!res.ok) throw new Error(`API returned ${res.status}`);
        const data = await res.json();

        typingEl.remove();
        this.appendMessage("bot", data.reply || "Sorry, er ging iets mis. Probeer het nog eens.");
      } catch (err) {
        typingEl.remove();
        this.appendMessage(
          "bot",
          "Er ging iets mis bij het verbinden met de adviseur. Probeer het over even nog eens."
        );
        console.error("Studiekompas widget error:", err);
      } finally {
        this.isSending = false;
        this.sendBtn.disabled = false;
      }
    }

    requestHuman() {
      this.sendMessage("Ik wil graag met een mens spreken in plaats van de AI.");
    }

    /**
     * Public helper: opens the widget (if closed) and sends a given message.
     * Used by external "try this" prompt buttons on a demo/landing page.
     * Respects the consent gate — does nothing until consent is accepted.
     */
    askExample(text) {
      if (!this.isOpen) {
        this.toggle();
      }
      if (!this.consentGiven) {
        return;
      }
      setTimeout(() => this.sendMessage(text), 250);
    }
  }

  customElements.define("studiekompas-widget", StudiekompasWidget);
})();