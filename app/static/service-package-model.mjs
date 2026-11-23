/** Display helpers shared by package administration and invitation purchase details. */
export const packageMoney = fen => `¥${(fen / 100).toFixed(2)}`;
export const rebateText = status => ({ unset: '未填写', pending: '待兑换', redeemed: '已兑换' })[status] || '未填写';
export function filterPackages(items, query, status) {
  const search = query.trim().toLocaleLowerCase();
  return items.filter(item => item.name.toLocaleLowerCase().includes(search)
    && (status === 'all' || item.enabled === (status === 'enabled')));
}

/** Upload pasted image files and replace the editor selection with Markdown links. */
export async function insertPastedImages(editor, files, upload) {
  const images = [...files].filter(file => ['image/png', 'image/jpeg', 'image/webp'].includes(file.type));
  let start = editor.selectionStart;
  let end = editor.selectionEnd;
  for (const file of images) {
    const result = await upload(file);
    const alt = (file.name || '粘贴图片').replace(/[\[\]\\\r\n]/g, '') || '粘贴图片';
    const markdown = `![${alt}](${result.url})`;
    if (editor.maxLength > 0 && editor.value.length - (end - start) + markdown.length > editor.maxLength)
      throw new Error('套餐详情已达到字数限制，图片链接无法插入');
    editor.setRangeText(markdown, start, end, 'end');
    start = end = editor.selectionEnd;
    editor.dispatchEvent(new Event('input', { bubbles: true }));
  }
  return images.length;
}
