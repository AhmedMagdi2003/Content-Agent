const notice = (text, error = false) => {
  const box = document.querySelector('#notice');
  box.textContent = text; box.hidden = false; box.classList.toggle('error', error);
  box.setAttribute('role', error ? 'alert' : 'status'); box.scrollIntoView({block: 'nearest'});
};
async function api(url, method = 'POST', body) {
  const headers = {'X-CSRF-Token': document.querySelector('meta[name=csrf-token]').content};
  if (!(body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch(url, {method, headers,
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail));
  return result;
}
function action(form, handler) {
  if (!form) return;
  form.addEventListener('submit', async event => {
    event.preventDefault(); const buttons = form.querySelectorAll('button');
    buttons.forEach(b => b.disabled = true);
    try { await handler(new FormData(form)); }
    catch (error) { notice(error.message, true); }
    finally { buttons.forEach(b => b.disabled = false); }
  });
}
action(document.querySelector('#content-form'), async data => {
  notice('Preparing three drafts from your source facts…');
  const result = await api('/api/v1/content', 'POST', {source: data.get('source')});
  location.href = '/content/' + result.id;
});
const draftForm = document.querySelector('#draft-form');
let dirty = false;
draftForm?.addEventListener('input', () => { dirty = true; });
action(draftForm, async data => {
  await api(`/api/v1/content/${draftForm.dataset.id}`, 'PUT', {revision: Number(draftForm.dataset.revision),
    drafts: {linkedin: data.get('linkedin'), newsletter: data.get('newsletter'), website: data.get('website')},
    channels: data.getAll('channels')});
  location.reload();
});
async function publish(retry) {
  if (dirty) { notice('Save your edits as a new revision before approving or retrying.', true); return; }
  const buttons = draftForm.querySelectorAll('button'); buttons.forEach(b => b.disabled = true);
  try {
    notice('Sending the approved revision to the selected test destinations…');
    const result = await api(`/api/v1/content/${draftForm.dataset.id}/${retry ? 'retry' : 'approve-and-publish'}`, 'POST', {
      revision: Number(draftForm.dataset.revision), digest: draftForm.dataset.digest});
    notice(result.map(p => `${p.channel}: ${p.status}${p.error ? ' · ' + p.error : ''}`).join('\n'), result.some(p => p.status === 'failed'));
    // Reload shows durable per-channel results; the live status message is read first.
    setTimeout(() => location.reload(), 1600);
  } catch (error) { notice(error.message, true); } finally { buttons.forEach(b => b.disabled = false); }
}
document.querySelector('#approve-publish')?.addEventListener('click', () => publish(false));
document.querySelector('#retry-publish')?.addEventListener('click', () => publish(true));
const rejectForm = document.querySelector('#reject-form');
action(rejectForm, async data => {
  await api(`/api/v1/content/${rejectForm.dataset.id}/reject`, 'POST', {
    revision: Number(rejectForm.dataset.revision), justification: data.get('justification')});
  location.reload();
});
document.querySelector('#logout')?.addEventListener('click', async () => { await api('/logout'); location.href = '/login'; });
