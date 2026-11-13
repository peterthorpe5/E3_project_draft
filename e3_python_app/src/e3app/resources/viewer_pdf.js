/** Local PDF image and text support for the offline protein viewers. */
"use strict";
(() => {
  const encoder = new TextEncoder();
  const bytes = value => typeof value === "string" ? encoder.encode(value) : value;
  function join(parts) {
    const data = parts.map(bytes);
    const joined = new Uint8Array(data.reduce((total, part) => total + part.length, 0));
    let offset = 0;
    for (const part of data) {
      joined.set(part, offset);
      offset += part.length;
    }
    return joined;
  }

  function buildPdf(objects) {
    const parts = [bytes("%PDF-1.4\n")];
    const offsets = [0];
    let length = parts[0].length;
    for (const [index, body] of objects.entries()) {
      offsets.push(length);
      const object = join([`${index + 1} 0 obj\n`, body, "\nendobj\n"]);
      parts.push(object);
      length += object.length;
    }
    let table = `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
    for (const offset of offsets.slice(1)) table += `${String(offset).padStart(10, "0")} 00000 n \n`;
    parts.push(bytes(table + `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\n` +
      `startxref\n${length}\n%%EOF\n`));
    return new Blob(parts, { type: "application/pdf" });
  }

  function downloadBlob(blob, name) {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  function safePdfName(value) {
    return String(value || "protein").replace(/[^A-Za-z0-9_.-]+/g, "_").slice(0, 140);
  }

  function pdfText(value) {
    return String(value).replace(/[–—]/g, "-").replace(/·/g, "|").replace(/α/g, "alpha")
      .replace(/[^\x20-\x7E]/g, "?").replace(/([\\()])/g, "\\$1");
  }

  /** Build a landscape PDF with the current canvas and a selectable-text colour key. */
  function canvasPdf({ canvas, title, subtitle = "", legend = [], background = "#fff" }) {
    if (!canvas.width || !canvas.height) throw new Error("The structure view is empty.");
    const imageCanvas = document.createElement("canvas");
    imageCanvas.width = canvas.width;
    imageCanvas.height = canvas.height;
    const context = imageCanvas.getContext("2d");
    context.fillStyle = background;
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(canvas, 0, 0);
    const jpeg = imageCanvas.toDataURL("image/jpeg", .97).split(",")[1];
    const image = Uint8Array.from(atob(jpeg), character => character.charCodeAt(0));
    const pageWidth = 842, pageHeight = 595, margin = 25;
    const entries = legend.slice(0, 16);
    const legendRows = Math.ceil(entries.length / 2);
    const bottom = margin + legendRows * 17 + (legendRows ? 10 : 0);
    const top = pageHeight - (subtitle ? 70 : 54);
    const scale = Math.min((pageWidth - 2 * margin) / canvas.width,
      (top - bottom) / canvas.height);
    const width = canvas.width * scale;
    const height = canvas.height * scale;
    const x = (pageWidth - width) / 2;
    const y = bottom + (top - bottom - height) / 2;
    const commands = [
      `q ${width.toFixed(2)} 0 0 ${height.toFixed(2)} ${x.toFixed(2)} ${y.toFixed(2)} cm /Im0 Do Q`,
      `BT /F1 16 Tf ${margin} 560 Td (${pdfText(String(title).slice(0, 86))}) Tj ET`,
    ];
    if (subtitle) commands.push(
      `BT /F1 10 Tf ${margin} 542 Td (${pdfText(String(subtitle).slice(0, 126))}) Tj ET`,
    );
    entries.forEach(({ colour, label }, index) => {
      const left = margin + (index % 2) * 397;
      const line = bottom - 16 - Math.floor(index / 2) * 17;
      const hex = /^#[\da-f]{6}$/i.test(colour) ? colour.slice(1) : "243246";
      const rgb = [0, 2, 4].map(offset =>
        (parseInt(hex.slice(offset, offset + 2), 16) / 255).toFixed(3)).join(" ");
      commands.push(
        `q ${rgb} rg 0.14 0.20 0.28 RG ${left} ${line - 1} 9 9 re B Q`,
        `BT /F1 10 Tf ${left + 15} ${line} Td (${pdfText(String(label).slice(0, 72))}) Tj ET`,
      );
    });
    const stream = commands.join("\n");
    return buildPdf([
      "<< /Type /Catalog /Pages 2 0 R >>",
      "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] ` +
        "/Resources << /XObject << /Im0 4 0 R >> /Font << /F1 6 0 R >> >> /Contents 5 0 R >>",
      join([
        `<< /Type /XObject /Subtype /Image /Width ${canvas.width} /Height ${canvas.height} ` +
          `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${image.length} >>\nstream\n`,
        image, "\nendstream",
      ]),
      `<< /Length ${bytes(stream).length} >>\nstream\n${stream}\nendstream`,
      "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]);
  }

  globalThis.E3ViewerPdf = { buildPdf, downloadBlob, safePdfName, pdfText, canvasPdf };
})();
