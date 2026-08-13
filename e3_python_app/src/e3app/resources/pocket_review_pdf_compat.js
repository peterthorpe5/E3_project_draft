"use strict";
(() => {
const pdfEncoder = new TextEncoder();
function pdfBytes(value) {
  return typeof value === "string" ? pdfEncoder.encode(value) : value;
}
function pdfJoin(parts) {
  const size = parts.reduce((total, part) => total + pdfBytes(part).length, 0);
  const joined = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) {
    const bytes = pdfBytes(part);
    joined.set(bytes, offset);
    offset += bytes.length;
  }
  return joined;
}
function buildPdf(objects) {
  const parts = [pdfBytes("%PDF-1.4\n")];
  const offsets = [0];
  let length = parts[0].length;
  objects.forEach((body, index) => {
    offsets.push(length);
    const object = pdfJoin([`${index + 1} 0 obj\n`, body, "\nendobj\n"]);
    parts.push(object);
    length += object.length;
  });
  const xref = length;
  let table = `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let index = 1; index < offsets.length; index += 1) {
    table += `${String(offsets[index]).padStart(10, "0")} 00000 n \n`;
  }
  parts.push(pdfBytes(
    table + `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\n` +
    `startxref\n${xref}\n%%EOF\n`
  ));
  return new Blob(parts, {type: "application/pdf"});
}
function downloadBlob(blob, name) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
function safePdfName(value) {
  return String(value || "e3_group").replace(/[^A-Za-z0-9_.-]+/g, "_");
}
function jpegBytes(url) {
  const binary = atob(url.split(",")[1]);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}
function downloadCurrentViewPdf() {
  draw();
  const image = jpegBytes(canvas.toDataURL("image/jpeg", 0.95));
  const pageWidth = 842;
  const pageHeight = 595;
  const scale = Math.min(792 / canvas.width, 545 / canvas.height);
  const width = canvas.width * scale;
  const height = canvas.height * scale;
  const x = (pageWidth - width) / 2;
  const y = (pageHeight - height) / 2;
  const imageBody = pdfJoin([
    `<< /Type /XObject /Subtype /Image /Width ${canvas.width} ` +
      `/Height ${canvas.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 ` +
      `/Filter /DCTDecode /Length ${image.length} >>\nstream\n`,
    image,
    "\nendstream"
  ]);
  const command = `q ${width.toFixed(2)} 0 0 ${height.toFixed(2)} ` +
    `${x.toFixed(2)} ${y.toFixed(2)} cm /Im0 Do Q`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] ` +
      "/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>",
    imageBody,
    `<< /Length ${pdfBytes(command).length} >>\nstream\n${command}\nendstream`
  ];
  downloadBlob(
    buildPdf(objects),
    `${safePdfName(data.group_key.primary_group_id)}_3d_view.pdf`
  );
}
function pdfText(value) {
  return String(value).replace(/[^\x20-\x7E]/g, "?").replace(/([\\()])/g, "\\$1");
}
function downloadAlignmentPdf() {
  if (data.alignment.status !== "AVAILABLE") {
    return;
  }
  const records = data.alignment.records || [];
  const blockSize = 90;
  const rowsPerPage = 42;
  const pages = [];
  for (let start = 0; start < data.alignment.alignment_length; start += blockSize) {
    for (let first = 0; first < records.length; first += rowsPerPage) {
      const lines = [
        `ARIA E3 MAFFT alignment: ${data.group_key.primary_group_id}`,
        `Columns ${start + 1}-${Math.min(
          start + blockSize,
          data.alignment.alignment_length
        )}`,
        ""
      ];
      for (const record of records.slice(first, first + rowsPerPage)) {
        const label = `${record.is_reference ? "*" : " "}${record.accession} ` +
          `${record.species}`;
        lines.push(
          `${label.slice(0, 28).padEnd(28, " ")} ` +
          record.sequence.slice(start, start + blockSize)
        );
      }
      pages.push(lines);
    }
  }
  if (pages.length === 0) {
    return;
  }
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"
  ];
  const kids = [];
  pages.forEach((lines, index) => {
    const pageObject = 4 + index * 2;
    const contentObject = pageObject + 1;
    kids.push(`${pageObject} 0 R`);
    const commands = "BT /F1 6 Tf 24 570 Td 8 TL " +
      lines.map((line) => `(${pdfText(line)}) Tj T*`).join(" ") + " ET";
    objects.push(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] ` +
      `/Resources << /Font << /F1 3 0 R >> >> /Contents ${contentObject} 0 R >>`
    );
    objects.push(
      `<< /Length ${pdfBytes(commands).length} >>\nstream\n` +
      `${commands}\nendstream`
    );
  });
  objects[1] = `<< /Type /Pages /Kids [${kids.join(" ")}] ` +
    `/Count ${pages.length} >>`;
  downloadBlob(
    buildPdf(objects),
    `${safePdfName(data.group_key.primary_group_id)}_mafft_alignment.pdf`
  );
}
document.getElementById("downloadViewPdf").onclick = downloadCurrentViewPdf;
document.getElementById("downloadAlignmentPdf").onclick = downloadAlignmentPdf;
})();
