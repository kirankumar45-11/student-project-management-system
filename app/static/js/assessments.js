function updateTotal() {
  const p = parseFloat(document.getElementById('presentation_score')?.value) || 0;
  const r = parseFloat(document.getElementById('report_score')?.value) || 0;
  const i = parseFloat(document.getElementById('implementation_score')?.value) || 0;
  const tot = Math.min(100, Math.max(0, p + r + i));
  const el = document.getElementById('totalPreview');
  if (el) el.textContent = tot.toFixed(1);
}
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('presentation_score')?.addEventListener('input', updateTotal);
  document.getElementById('report_score')?.addEventListener('input', updateTotal);
  document.getElementById('implementation_score')?.addEventListener('input', updateTotal);
  updateTotal();
});
