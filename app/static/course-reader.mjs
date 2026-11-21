import {el,button} from './ui.js?v=20261114-ui-v17';

let catalogPreference=null,readerSession=null;

/** Exit reading mode when leaving courses, including while the next lesson is loading. */
export function exitCourseReaderFullscreen(){
  const session=readerSession;if(!session)return;
  readerSession=null;session.removeListeners();
  session.host.classList.remove('course-reader-host-fullscreen');
  document.body.classList.remove('course-reader-focus-active');
  session.sync?.();window.scrollTo(0,session.pageScroll);
  if(document.fullscreenElement===session.host){
    void document.exitFullscreen().catch(()=>{/* Browser navigation may already have exited fullscreen. */});
  }
}

function beginReaderSession(host,fallback,pageScroll){
  const session={host,fallback,pageScroll,content:null,sync:null,removeListeners:()=>{}};
  readerSession=session;host.classList.toggle('course-reader-host-fullscreen',true);
  document.body.classList.toggle('course-reader-focus-active',fallback);
  const onFullscreen=()=>{
    if(!fallback&&document.fullscreenElement!==host)exitCourseReaderFullscreen();
  };
  const onKey=event=>{
    if(event.key==='Escape'&&fallback){event.preventDefault();exitCourseReaderFullscreen();}
    if(event.key==='Tab'&&fallback&&session.content){
      const controls=[...session.content.querySelectorAll('button:not(:disabled),a[href],video[controls],[tabindex="0"]')].filter(node=>!node.hidden&&node.getClientRects().length);
      const first=controls[0],last=controls.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  };
  document.addEventListener('fullscreenchange',onFullscreen);document.addEventListener('keydown',onKey);
  session.removeListeners=()=>{document.removeEventListener('fullscreenchange',onFullscreen);document.removeEventListener('keydown',onKey);};
}

/** Mount reading controls; dispose them before replacing the lesson DOM. */
export function mountCourseReader({layout,nav,content,host=content,title}){
  const narrow=window.matchMedia('(max-width: 760px)');
  let disposed=false,wasFullscreen=false,readingScroll=0;
  const icon=(path)=>{const node=el('span','','course-reader-icon');node.setAttribute('aria-hidden','true');node.innerHTML=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"/></svg>`;return node;};
  const rail=el('div','','course-reader-rail');
  const toggle=button('',()=>setCatalog(true),'course-reader-restore');
  toggle.append(icon('m9 6 6 6-6 6'),el('span','目录'));
  toggle.title='展开课程目录';toggle.setAttribute('aria-label','展开课程目录');rail.append(toggle);content.prepend(rail);
  const navHeading=nav.querySelector('.course-section-title');
  const collapse=button('',()=>setCatalog(false),'course-reader-catalog-heading');
  collapse.append(el('span','本课程','course-reader-catalog-title'));
  const progress=navHeading?.querySelector('.course-muted');if(progress)collapse.append(progress);
  collapse.append(icon('m14 6-6 6 6 6'));
  collapse.title='收起课程目录';collapse.setAttribute('aria-label','收起课程目录');
  navHeading?.replaceChildren(collapse);
  const fullscreen=button('',async()=>{
    if(isFullscreen()){exitCourseReaderFullscreen();return;}
    const pageScroll=window.scrollY;
    readingScroll=Math.max(0,-content.getBoundingClientRect().top);
    if(host.requestFullscreen){
      try{
        await host.requestFullscreen();
        if(disposed){if(document.fullscreenElement===host)await document.exitFullscreen();return;}
        beginReaderSession(host,false,pageScroll);attachSession();syncFullscreen();return;
      }catch(error){
        // Embedded browsers can deny native fullscreen; retain an in-page reading mode.
        if(disposed)return;
      }
    }
    beginReaderSession(host,true,pageScroll);attachSession();syncFullscreen();
  },'course-reader-fullscreen');
  const fullscreenIcon=icon('M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5');fullscreen.append(fullscreenIcon);
  const hint=el('span','Esc 退出','course-reader-exit-hint');hint.hidden=true;
  const actions=el('div','','course-reader-actions');actions.append(hint,fullscreen);
  const reading=content.querySelector('.course-study-reading');
  if(reading){
    const header=el('header','','course-reading-heading');const heading=reading.querySelector('h2');
    if(heading)header.append(heading);header.append(actions);reading.prepend(header);
  }else{const tools=el('div','','course-reader-media-tools');tools.append(actions);content.prepend(tools);}
  nav.id='course-study-catalog';toggle.setAttribute('aria-controls',nav.id);
  const navContent=nav.querySelector('.course-study-nav-content');
  if(navContent){navContent.id='course-study-catalog-items';collapse.setAttribute('aria-controls',navContent.id);}
  content.setAttribute('aria-label',title);
  const isFullscreen=()=>readerSession?.host===host;
  function attachSession(){if(isFullscreen()){readerSession.content=content;readerSession.sync=syncFullscreen;}}
  function setCatalog(open,remember=true){
    if(remember)catalogPreference=open;
    nav.hidden=!open;layout.classList.toggle('is-catalog-collapsed',!open);
    rail.hidden=open||isFullscreen();
    toggle.setAttribute('aria-expanded',String(open));collapse.setAttribute('aria-expanded',String(open));
    if(!open&&nav.contains(document.activeElement))toggle.focus({preventScroll:true});
    if(open&&rail.contains(document.activeElement))collapse.focus({preventScroll:true});
  }
  function syncFullscreen(){
    if(disposed)return;
    const active=isFullscreen();
    content.classList.toggle('is-reader-fullscreen',active);
    fullscreen.title=active?'退出全屏':'全屏阅读';fullscreen.setAttribute('aria-label',fullscreen.title);
    fullscreenIcon.innerHTML=active?'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h5V3m8 0v5h5M8 21v-5H3m18 0h-5v5"/></svg>':'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/></svg>';
    fullscreen.setAttribute('aria-pressed',String(active));hint.hidden=!active;rail.hidden=active||!nav.hidden;
    if(active&&!wasFullscreen){content.scrollTop=readingScroll;fullscreen.focus({preventScroll:true});}
    if(!active&&wasFullscreen)fullscreen.focus({preventScroll:true});
    wasFullscreen=active;
  }
  const onResize=()=>{if(catalogPreference===null)setCatalog(!narrow.matches,false);};
  attachSession();setCatalog(catalogPreference??!narrow.matches,false);syncFullscreen();
  narrow.addEventListener('change',onResize);
  return ({preserveFullscreen=false}={})=>{
    disposed=true;narrow.removeEventListener('change',onResize);
    content.classList.remove('is-reader-fullscreen');
    if(isFullscreen()){
      readerSession.content=null;readerSession.sync=null;
      if(!preserveFullscreen)exitCourseReaderFullscreen();
    }
  };
}
