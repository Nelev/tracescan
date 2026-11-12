/**
 * A CSS color token as RGB, for canvases that cannot take the tokens as they are: they are oklch,
 * which three.js cannot parse and a 2D canvas cannot blend with an alpha of its own. The browser
 * paints one pixel with the token and the pixel is read back. Some tokens are translucent (the
 * glass card, the hairline border), so the pixel is first painted with the opaque page background
 * and the token composited over it: the color it shows on the page, not its raw hue.
 */
export function tokenRgb(name: string): readonly [number, number, number] {
  const style = getComputedStyle(document.documentElement);
  const value = style.getPropertyValue(name).trim();
  const page = style.getPropertyValue("--background").trim();
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return [128, 128, 128];
  context.fillStyle = "#808080";
  context.fillStyle = page;
  context.fillRect(0, 0, 1, 1);
  context.fillStyle = value;
  context.fillRect(0, 0, 1, 1);
  const [r, g, b] = context.getImageData(0, 0, 1, 1).data;
  return [r, g, b];
}
