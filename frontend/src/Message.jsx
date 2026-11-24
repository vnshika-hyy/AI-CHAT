export function UserMessage({ content }) {
  return (
    <div className="row row-user">
      <div className="bubble-user" data-testid="user-message">{content}</div>
    </div>
  );
}

export function ErrorMessage({ content }) {
  return (
    <div className="row">
      <div className="bubble-error" role="alert" data-testid="error-message">{content}</div>
    </div>
  );
}

export function AssistantMessage({ content, metadata }) {
  const cached = metadata.resolution_source === "LLM_CACHE";
  return (
    <div className="row">
      <article className={`bubble-assistant ${cached ? "is-cache" : "is-live"}`} data-testid="assistant-message">
        <div className="reply">{content}</div>
        <dl className="meta">
          <div className="meta-item">
            <dt>Source</dt>
            <dd>
              <span className={`badge ${cached ? "badge-cache" : "badge-live"}`} data-testid="meta-source">
                {metadata.resolution_source}
              </span>
            </dd>
          </div>
          <div className="meta-item">
            <dt>Model</dt>
            <dd data-testid="meta-model">{metadata.model}</dd>
          </div>
          <div className="meta-item">
            <dt>Latency</dt>
            <dd data-testid="meta-latency">{metadata.latency_ms} ms</dd>
          </div>
          <div className="meta-item">
            <dt>Input tokens</dt>
            <dd data-testid="meta-input-tokens">{metadata.input_tokens}</dd>
          </div>
          <div className="meta-item">
            <dt>Output tokens</dt>
            <dd data-testid="meta-output-tokens">{metadata.output_tokens}</dd>
          </div>
          <div className="meta-item">
            <dt>Key</dt>
            <dd data-testid="meta-key">{metadata.key_id ?? "none (cached)"}</dd>
          </div>
          <div className="meta-item">
            <dt>Fallbacks</dt>
            <dd data-testid="meta-fallbacks">{metadata.fallback_attempts}</dd>
          </div>
        </dl>
      </article>
    </div>
  );
}
