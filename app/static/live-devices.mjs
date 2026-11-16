/** Own one preview stream; superseded or closed permission requests immediately stop late tracks. */
export function mediaLease(getUserMedia) {
  let generation=0,current=null;
  function release(){generation++;current?.getTracks().forEach(track=>track.stop());current=null;}
  async function acquire(constraints){
    release();const request=generation;const stream=await getUserMedia(constraints);
    if(request!==generation){stream.getTracks().forEach(track=>track.stop());return null;}
    current=stream;return{stream,isCurrent:()=>request===generation};
  }
  return{acquire,release};
}
