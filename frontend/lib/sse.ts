export type SseMessage = { event: string; data: string };

/**
 * Decodes a `text/event-stream` body into messages, one per blank-line-terminated block.
 * Comment lines (the server's `: ping` keepalives) carry no field and are ignored. Cancels the
 * body when the consumer stops, which closes the connection.
 */
export async function* readSse(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      // stream: true keeps a multi-byte character split across two chunks intact.
      buffer = (buffer + decoder.decode(value, { stream: true })).replaceAll(
        "\r\n",
        "\n",
      );
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? ""; // the block still being received
      for (const block of blocks) {
        const message = parseBlock(block);
        if (message) yield message;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
}

function parseBlock(block: string): SseMessage | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length > 0 ? { event, data: data.join("\n") } : null;
}
