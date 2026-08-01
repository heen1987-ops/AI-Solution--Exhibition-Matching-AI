const encoder = new TextEncoder();

async function digest(value: string): Promise<Uint8Array> {
  const bytes = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return new Uint8Array(bytes);
}

function sameBytes(left: Uint8Array, right: Uint8Array): boolean {
  if (left.byteLength !== right.byteLength) return false;
  let difference = 0;
  for (let index = 0; index < left.byteLength; index += 1) {
    difference |= left[index]! ^ right[index]!;
  }
  return difference === 0;
}

export async function hasValidInternalToken(req: Request): Promise<boolean> {
  const configured = Netlify.env.get("AI_INTERNAL_TOKEN");
  const supplied = req.headers.get("x-ai-internal-token");
  if (!configured || !supplied) return false;
  return sameBytes(await digest(configured), await digest(supplied));
}

