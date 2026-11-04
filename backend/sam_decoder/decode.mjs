// Decodes raw SAM 3.1 video output with Meta's official parser into a compact form
// Python can load with numpy: <out>.json (record index) + <out>.bin (bit-packed masks).
// Large masks arrive downscaled (max 1024px a side); [l, t, r, b) is the box they cover.
// The Python parser decodes masks pixel by pixel and is far too slow for full videos.
//
// usage: node decode.mjs <sam_output.txt> <out_prefix>
import { closeSync, openSync, readFileSync, writeFileSync, writeSync } from "node:fs";
import { decodeMaskToRaster, formats, frameIndexOf } from "@meta-sam/parser";

const [, , input, outPrefix] = process.argv;
const parser = formats.segmentation.video().createParser();
parser.push(readFileSync(input, "utf8"), { emit: false });
const { result } = parser.finish({ status: "completed" });

// Masks go to disk as they are packed, so memory holds one raster at a time.
const bin = openSync(`${outPrefix}.bin`, "w");
const index = [];
let offset = 0;
for (const rec of result.records) {
  if (rec.kind !== "mask") continue;
  const frame = frameIndexOf(rec);
  if (frame === undefined) continue;
  const { width: w, height: h } = rec.mask;
  const raster = decodeMaskToRaster(rec.mask);
  const packed = new Uint8Array(Math.ceil((w * h) / 8));
  for (let i = 0; i < raster.length; i++) {
    if (raster[i]) packed[i >> 3] |= 0x80 >> (i & 7);
  }
  index.push({
    f: frame,
    id: rec.objectId,
    l: Math.round(rec.bounds.left),
    t: Math.round(rec.bounds.top),
    r: Math.round(rec.bounds.right),
    b: Math.round(rec.bounds.bottom),
    w,
    h,
    o: offset,
    c: rec.confidence ?? null,
  });
  writeSync(bin, packed);
  offset += packed.length;
}

closeSync(bin);
writeFileSync(`${outPrefix}.json`, JSON.stringify({ records: index, diagnostics: result.diagnostics.length }));
console.log(`${index.length} masks`);
