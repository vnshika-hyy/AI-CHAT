// The base URL is baked in at build time: VITE_API_URL=https://your-backend.onrender.com
const BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");

export class ApiError extends Error {}

function describeError(status, data) {
  if (status === 503) {
    return "All AI providers are unavailable right now. Please try again in a moment.";
  }
  if (status === 422) {
    const first = Array.isArray(data?.detail) ? data.detail[0] : null;
    const field = first?.loc?.[first.loc.length - 1];
    if (field === "message") {
      return "Your message must be between 1 and 4000 characters.";
    }
    if (field === "session_id") {
      return "The chat session is invalid. Start a new chat and try again.";
    }
    return "The request was not valid. Check your message and try again.";
  }
  if (typeof data?.detail === "string") return data.detail;
  return `Something went wrong (HTTP ${status}). Please try again.`;
}

export async function sendChat({ sessionId, message, systemPrompt, simulate }) {
  const headers = { "Content-Type": "application/json" };
  if (simulate && simulate.trim()) headers["X-Simulate-Failure"] = simulate.trim();

  const body = { session_id: sessionId, message };
  if (systemPrompt && systemPrompt.trim()) body.system_prompt = systemPrompt.trim();

  let res;
  try {
    res = await fetch(`${BASE}/chat`, { method: "POST", headers, body: JSON.stringify(body) });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.");
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body: fall through to the generic message */
  }
  if (!res.ok) throw new ApiError(describeError(res.status, data));
  return data;
}
