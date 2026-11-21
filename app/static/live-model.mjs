/** Parse only supported classroom routes with safe database identifiers. */
export function liveRoute(hash) {
  const markdown = /^#view=live\/markdown\/([1-9]\d*)\/(new|[1-9]\d*)$/.exec(hash || '');
  if (markdown) {
    const id=Number(markdown[1]),assetId=markdown[2]==='new'?null:Number(markdown[2]);
    if(Number.isSafeInteger(id)&&(assetId===null||Number.isSafeInteger(assetId)))return {kind:'markdown',id,assetId};
  }
  const editor = /^#view=live\/editor\/(new|[1-9]\d*)(?:\/(info|content|publish))?$/.exec(hash || '');
  if (editor) {
    const id = editor[1] === 'new' ? null : Number(editor[1]);
    if (id === null || Number.isSafeInteger(id))
      return {kind:'editor',id,step:editor[2]||'info'};
  }
  const named = /^#view=live\/(plaza|manage)$/.exec(hash || '');
  if (named) return {kind:named[1] === 'plaza' ? 'public' : 'manage'};
  const match = /^#view=live\/(course|study|lesson|preview)\/([1-9]\d*)$/.exec(hash || '');
  if (!match || !Number.isSafeInteger(Number(match[2]))) return {kind:'list'};
  return {kind:match[1],id:Number(match[2])};
}
/** Keep course-management routes inside the admin course workspace. */
export function courseCatalogScope(kind, adminMode) {
  if (adminMode) return 'managed';
  return kind === 'public' ? 'public' : 'mine';
}
/** Format a nonnegative duration for the compact classroom clock. */
export function elapsed(seconds) {
  const value=Math.max(0,Math.floor(Number(seconds)||0));
  const parts=[Math.floor(value/3600),Math.floor(value/60)%60,value%60].map(x=>String(x).padStart(2,'0'));
  return parts[0]==='00'?parts.slice(1).join(':'):parts.join(':');
}
/** Hosts and raised hands precede other participants, preserving original tie order. */
export function orderedMembers(members) {
  return [...members].sort((a,b)=>Number(Boolean(b.is_host))-Number(Boolean(a.is_host)) || Number(Boolean(b.hand||b.request_share))-Number(Boolean(a.hand||a.request_share)));
}
export function recordingText(status) {
  return ({idle:'尚未录制',starting:'正在启动录制',recording:'正在录制',stopping:'正在停止录制',processing:'回放处理中',ready:'可观看',completed:'可观看',unknown:'录制状态待确认',failed:'录制失败'})[status]||'尚未录制';
}
export function mayJoin(lesson) { return lesson.status==='live' && lesson.configured===true; }
/** Finished lessons still refresh while a recording awaits its terminal result. */
export function needsLessonUpdates(lesson) {
  return lesson.status!=='ended'||(lesson.recordings||[]).some(record=>['starting','recording','stopping','processing','unknown'].includes(record.status));
}
export function liveDate(timestamp) {
  return timestamp ? new Date(timestamp*1000).toLocaleString('zh-CN',{month:'long',day:'numeric',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false}):'时间待安排';
}
