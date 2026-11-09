export const frameLimit = 1572864;
export const accountId =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function accountFrame(data: Uint8Array): string {
  const header = [
    137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 4, 0, 0,
    0, 3, 0,
  ];
  if (
    data.length < 33 ||
    data.length > frameLimit ||
    !header.every((byte, i) => data[i] === byte)
  ) {
    throw new Error("Invalid account browser frame");
  }
  let binary = "";
  for (let i = 0; i < data.length; i += 8192) {
    binary += String.fromCharCode(...data.subarray(i, i + 8192));
  }
  return "data:image/png;base64," + btoa(binary);
}
