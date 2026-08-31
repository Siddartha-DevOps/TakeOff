function pdfObject(number, body) {
  return `${number} 0 obj\n${body}\nendobj\n`;
}

/** A one-page vector plan with three closed rooms and dimension linework. */
export function vectorFloorPlanPdf() {
  const content = [
    '0.8 w',
    '50 70 160 200 re S',
    '210 70 160 200 re S',
    '370 70 160 200 re S',
    '50 300 m 530 300 l S',
    '50 290 m 50 310 l S',
    '530 290 m 530 310 l S',
    'BT /F1 14 Tf 80 180 Td (ROOM A) Tj ET',
    'BT /F1 14 Tf 240 180 Td (ROOM B) Tj ET',
    'BT /F1 14 Tf 400 180 Td (ROOM C) Tj ET',
    'BT /F1 10 Tf 250 320 Td (40 FT) Tj ET',
  ].join('\n');
  const objects = [
    pdfObject(1, '<< /Type /Catalog /Pages 2 0 R >>'),
    pdfObject(2, '<< /Type /Pages /Kids [3 0 R] /Count 1 >>'),
    pdfObject(3, '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>'),
    pdfObject(4, `<< /Length ${Buffer.byteLength(content, 'ascii')} >>\nstream\n${content}\nendstream`),
    pdfObject(5, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'),
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  for (const object of objects) {
    offsets.push(Buffer.byteLength(pdf, 'ascii'));
    pdf += object;
  }
  const xref = Buffer.byteLength(pdf, 'ascii');
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.slice(1).map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(pdf, 'ascii');
}
