/** Close open course menus unless the click toggles one of their summaries. */
export function closeCourseMenusOutsideClick(event,menus){
  const summary=event.target.closest?.('summary');
  const toggled=menus.includes(summary?.parentElement)?summary.parentElement:null;
  for(const menu of menus)if(menu!==toggled)menu.open=false;
}
