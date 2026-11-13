"use strict";
(() => {
const { buildPdf, downloadBlob, safePdfName, pdfText, canvasPdf } = globalThis.E3ViewerPdf;
function downloadCurrentViewPdf() {
  draw();
  const group = data.group_key.primary_group_id;
  downloadBlob(canvasPdf({
    canvas, title: `${group} · Cα structure`,
    background: getComputedStyle(canvas).backgroundColor,
  }), `${safePdfName(group)}_3d_view.pdf`);
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
      `<< /Length ${new TextEncoder().encode(commands).length} >>\nstream\n` +
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
