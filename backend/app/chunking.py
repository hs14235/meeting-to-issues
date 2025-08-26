def to_chunks(text: str, approx_tokens: int = 400):
    """
    Naive paragraph joiner: builds ~400-word chunks.
    Good enough for MVP; replace with token-aware later.
    """
    paras = [p.strip() for p in text.splitlines() if p.strip()]
    chunks, buf, wc = [], [], 0
    for p in paras:
        buf.append(p)
        wc += len(p.split())
        if wc >= approx_tokens:
            chunks.append("\n".join(buf))
            buf, wc = [], 0
    if buf:
        chunks.append("\n".join(buf))
    return chunks
