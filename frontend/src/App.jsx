import { useEffect, useRef, useState } from "react";
import { sendChat, ApiError } from "./api.js";
import { AssistantMessage, ErrorMessage, UserMessage } from "./Message.jsx";

const SHOW_TEST_TOOLS = import.meta.env.VITE_SHOW_TEST_TOOLS !== "false";

function newSessionId() {
  const rand =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10);
  return `s-${rand}`;
}

export default function App() {
  const [sessionId, setSessionId] = useState(newSessionId); // new session on every page load
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const bottomRef = useRef(null);
  const nextId = useRef(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  const push = (item) => setMessages((prev) => [...prev, { id: nextId.current++, ...item }]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    push({ role: "user", content: text });
    setLoading(true);
    const slowTimer = setTimeout(() => setSlow(true), 6000);
    try {
      const data = await sendChat({ sessionId, message: text, systemPrompt, simulate });
      push({ role: "assistant", content: data.reply, metadata: data.metadata });
    } catch (err) {
      push({
        role: "error",
        content: err instanceof ApiError ? err.message : "Unexpected error. Please try again.",
      });
    } finally {
      clearTimeout(slowTimer);
      setSlow(false);
      setLoading(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  }

  function newChat() {
    setSessionId(newSessionId());
    setMessages([]);
    setInput("");
  }

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>AI Chat</h1>
          <p className="session">Session <span data-testid="session-id">{sessionId}</span></p>
        </div>
        <button type="button" className="ghost" onClick={newChat} data-testid="new-chat-button">
          New chat
        </button>
      </header>

      <main className="thread" aria-live="polite">
        {messages.length === 0 && !loading && (
          <section className="empty">
            <h2>Ask anything</h2>
            <p>Every reply shows where it came from, which model answered, how long it took and what it cost in tokens.</p>
          </section>
        )}
        {messages.map((m) =>
          m.role === "user" ? (
            <UserMessage key={m.id} content={m.content} />
          ) : m.role === "assistant" ? (
            <AssistantMessage key={m.id} content={m.content} metadata={m.metadata} />
          ) : (
            <ErrorMessage key={m.id} content={m.content} />
          )
        )}
        {loading && (
          <div className="row">
            <div className="pending" data-testid="loading">
              {slow ? "Still working. The server may be waking up…" : "Thinking…"}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      <footer className="composer">
        <details className="settings">
          <summary>Session settings</summary>
          <label htmlFor="system-prompt">System prompt</label>
          <textarea
            id="system-prompt"
            data-testid="system-prompt-input"
            rows={2}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="Optional. For example: You are a pirate. Answer in one sentence."
          />
          {SHOW_TEST_TOOLS && (
            <>
              <label htmlFor="simulate">Simulate key failure (for testing failover)</label>
              <input
                id="simulate"
                data-testid="simulate-input"
                value={simulate}
                onChange={(e) => setSimulate(e.target.value)}
                placeholder="key_1=429   or   key_1=429,key_2=500   or   *=429"
              />
            </>
          )}
        </details>
        <div className="input-row">
          <textarea
            data-testid="chat-input"
            aria-label="Message"
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Type a message. Enter to send, Shift+Enter for a new line."
          />
          <button type="button" className="send" data-testid="send-button" onClick={send} disabled={loading}>
            Send
          </button>
        </div>
      </footer>
    </div>
  );
}
