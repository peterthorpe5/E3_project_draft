(()=>{var M="#e32860";function _({sequence:m,query:h}){let r=h.replace(/\s/g,"");if(!r)return[];if(!/^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$/i.test(r))throw new Error("Use amino-acid letters, for example QWFAA.");let c=r.toUpperCase(),t=[];for(let i=m.indexOf(c);i!==-1;i=m.indexOf(c,i+1))t.push({start:i+1,end:i+c.length});return t}function V({sequence:m,query:h}){let r=new RegExp(h,"gi"),c=[];for(let t=r.exec(m);t;t=r.exec(m))t[0].length&&c.push({start:t.index+1,end:t.index+t[0].length}),r.lastIndex=t.index+1;return c}function z({sequence:m,query:h,onResult:r}){let c=`self.onmessage = ({ data }) => {
    try {
      self.postMessage({ matches: (${V.toString()})(data) });
    } catch (error) {
      self.postMessage({ error: error.message });
    }
  };`,t=URL.createObjectURL(new Blob([c],{type:"text/javascript"})),i;try{i=new Worker(t)}catch(n){throw URL.revokeObjectURL(t),new Error("Regular expression search is unavailable in this viewer.",{cause:n})}let x=setTimeout(()=>e({error:"This regular expression took too long. Try a simpler pattern."}),2e3);function y(){clearTimeout(x),i.onmessage=i.onerror=null,i.terminate(),URL.revokeObjectURL(t)}function e(n){y(),r(n)}return i.onmessage=({data:n})=>e(n),i.onerror=n=>{n.preventDefault(),e({error:"The viewer could not run this regular expression."})},i.postMessage({sequence:m,query:h}),y}function G(m){let h=[];for(let{start:r,end:c}of m){let t=h.at(-1);t&&r<=t.end+1?t.end=Math.max(t.end,c):h.push({start:r,end:c})}return h}function B(m){let h=new Set;for(let{start:r,end:c}of m)for(let t=r;t<=c;t+=1)h.add(t);return h}function O(m,h){let r=document.createElement("section");r.className="sequence-search",r.innerHTML=`
    <form>
      <label class="sequence-search-query">Amino-acid sequence
        <input type="text" placeholder="e.g. QWFAA" spellcheck="false" autocomplete="off">
      </label>
      <label class="sequence-search-regex" title="Use a pattern such as QW.A[AV]">
        <input type="checkbox"> Regular expression
      </label>
      <button type="submit">Find matches</button>
      <button type="button">Clear matches</button>
    </form>
    <div class="sequence-search-options">
      <label>Highlight
        <select aria-label="Highlight"><option value="all">All matches</option><option value="one">One match</option></select>
      </label>
      <label class="sequence-occurrence" hidden>Match number
        <input type="number" min="1" step="1" value="1">
      </label>
      <label class="trace-colour-picker">Match colour
        <input type="color" value="${M}">
      </label>
    </div>
    <p role="status" aria-live="polite"></p>`,m.appendChild(r);let c=r.querySelector("form"),t=c.querySelector('input[type="text"]'),i=c.querySelector('input[type="checkbox"]'),x=c.querySelector('button[type="submit"]'),y=c.querySelector('button[type="button"]'),e=r.querySelector("select"),n=r.querySelector('input[type="number"]'),s=r.querySelector('input[type="color"]'),p=r.querySelector("p"),u="",a=[],w=!1,v="",T="",S=null;function k(){let o=e.value==="one",d=Math.min(Math.max(1,Math.trunc(Number(n.value))||1),a.length);d&&(n.value=String(d)),n.max=String(a.length),n.parentElement.hidden=!o||!a.length,e.disabled=a.length<2,t.disabled=x.disabled=i.disabled=!u,y.disabled=!w&&!t.value;let f=o?a.slice(d-1,d):a,b=f.slice(0,8).map(({start:C,end:E})=>C===E?String(C):`${C}\u2013${E}`).join(", ")+(f.length>8?", \u2026":""),g=o&&a.length>1?`Match ${d} of ${a.length}`:`${a.length} ${a.length===1?"match":"matches"}`;p.textContent=u?S?"Searching\u2026":v||(a.length?`${g} \xB7 ${b}`:w?i.checked?"No matching residues.":"No exact matches.":""):"A verified sequence is unavailable for this structure.",h({ranges:G(f),colour:s.value,summary:p.textContent,query:T,regularExpression:i.checked})}function $({matches:o=[],error:d=""}){S=null,a=o,v=d,a.length<2&&(e.value="all"),k()}function R(){S?.(),S=null;let o=t.value;if(T=i.checked?o:o.replace(/\s/g,"").toUpperCase(),w=!!T,t.placeholder=i.checked?"e.g. QW.A[AV]":"e.g. QWFAA",i.checked?t.removeAttribute("maxlength"):t.maxLength=u.length+100,n.value="1",!u||!w){$({});return}try{i.checked?(S=z({sequence:u,query:o,onResult:$}),a=[],v="",k()):$({matches:_({sequence:u,query:o})})}catch(d){$({error:d.message})}}c.addEventListener("submit",o=>{o.preventDefault(),R()}),t.addEventListener("input",()=>{y.disabled=!w&&!t.value}),i.addEventListener("change",R);for(let o of[e,n,s])o.addEventListener("change",k);s.addEventListener("input",k);function l(){t.value="",e.value="all",R()}return y.addEventListener("click",l),{setSequence(o){u=o||"",R()},clear:l,resetColour(){s.value=M,k()},get colourChanged(){return s.value!==M}}}(()=>{let m=new TextEncoder,h=e=>typeof e=="string"?m.encode(e):e;function r(e){let n=e.map(h),s=new Uint8Array(n.reduce((u,a)=>u+a.length,0)),p=0;for(let u of n)s.set(u,p),p+=u.length;return s}function c(e){let n=[h(`%PDF-1.4
`)],s=[0],p=n[0].length;for(let[a,w]of e.entries()){s.push(p);let v=r([`${a+1} 0 obj
`,w,`
endobj
`]);n.push(v),p+=v.length}let u=`xref
0 ${e.length+1}
0000000000 65535 f 
`;for(let a of s.slice(1))u+=`${String(a).padStart(10,"0")} 00000 n 
`;return n.push(h(u+`trailer
<< /Size ${e.length+1} /Root 1 0 R >>
startxref
${p}
%%EOF
`)),new Blob(n,{type:"application/pdf"})}function t(e,n){let s=document.createElement("a");s.href=URL.createObjectURL(e),s.download=n,s.click(),setTimeout(()=>URL.revokeObjectURL(s.href),1e3)}function i(e){return String(e||"protein").replace(/[^A-Za-z0-9_.-]+/g,"_").slice(0,140)}function x(e){return String(e).replace(/[–—]/g,"-").replace(/·/g,"|").replace(/α/g,"alpha").replace(/[^\x20-\x7E]/g,"?").replace(/([\\()])/g,"\\$1")}function y({canvas:e,title:n,subtitle:s="",legend:p=[],background:u="#fff"}){if(!e.width||!e.height)throw new Error("The structure view is empty.");let a=document.createElement("canvas");a.width=e.width,a.height=e.height;let w=a.getContext("2d");w.fillStyle=u,w.fillRect(0,0,e.width,e.height),w.drawImage(e,0,0);let v=a.toDataURL("image/jpeg",.97).split(",")[1],T=Uint8Array.from(atob(v),L=>L.charCodeAt(0)),S=842,k=595,$=25,R=p.slice(0,16),l=Math.ceil(R.length/2),o=$+l*17+(l?10:0),d=k-(s?70:54),f=Math.min((S-2*$)/e.width,(d-o)/e.height),q=e.width*f,b=e.height*f,g=(S-q)/2,C=o+(d-o-b)/2,E=[`q ${q.toFixed(2)} 0 0 ${b.toFixed(2)} ${g.toFixed(2)} ${C.toFixed(2)} cm /Im0 Do Q`,`BT /F1 16 Tf ${$} 560 Td (${x(String(n).slice(0,86))}) Tj ET`];s&&E.push(`BT /F1 10 Tf ${$} 542 Td (${x(String(s).slice(0,126))}) Tj ET`),R.forEach(({colour:L,label:N},j)=>{let A=$+j%2*397,D=o-16-Math.floor(j/2)*17,W=/^#[\da-f]{6}$/i.test(L)?L.slice(1):"243246",Q=[0,2,4].map(F=>(parseInt(W.slice(F,F+2),16)/255).toFixed(3)).join(" ");E.push(`q ${Q} rg 0.14 0.20 0.28 RG ${A} ${D-1} 9 9 re B Q`,`BT /F1 10 Tf ${A+15} ${D} Td (${x(String(N).slice(0,72))}) Tj ET`)});let P=E.join(`
`);return c(["<< /Type /Catalog /Pages 2 0 R >>","<< /Type /Pages /Kids [3 0 R] /Count 1 >>",`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${S} ${k}] /Resources << /XObject << /Im0 4 0 R >> /Font << /F1 6 0 R >> >> /Contents 5 0 R >>`,r([`<< /Type /XObject /Subtype /Image /Width ${e.width} /Height ${e.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${T.length} >>
stream
`,T,`
endstream`]),`<< /Length ${h(P).length} >>
stream
${P}
endstream`,"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"])}globalThis.E3ViewerPdf={buildPdf:c,downloadBlob:t,safePdfName:i,pdfText:x,canvasPdf:y}})();var I=document.getElementById("e3ReviewHighlights"),H=document.getElementById("e3TerminalTrimControls");I&&H&&typeof draw=="function"&&typeof canvas<"u"&&K();function K(){let{group:m,targets:h}=JSON.parse(I.textContent),r=!!document.getElementById("alignmentData"),c="#c1a8ff",t=draw,i=[],x=new Set,y=new Set,e,n=document.createElement("section");n.className="e3-review-highlights",n.setAttribute("aria-label","Highlight domains and sequence matches"),n.innerHTML=`
    <style>
      .e3-review-highlights{padding:.7rem;border:1px solid #b9c9d4;border-radius:8px;
        margin:.75rem 0;background:#f7fafc}
      .e3-review-highlights h3{margin:0 0 .5rem}
      .e3-review-highlights label{display:block;margin:.3rem 0}
      .e3-review-highlights select,.e3-review-highlights input[type=text]{max-width:100%}
      .e3-review-highlights .sequence-search{border-top:1px solid #d7dee5;margin-top:.5rem;
        padding-top:.3rem}
      .e3-review-highlights .sequence-search p:empty,.e3-review-highlights [hidden]{display:none}
      .e3-review-highlights input[type=number]{width:5em}
      .e3-review-highlights .trace-colour-picker{display:flex;align-items:center;gap:.4rem}
    </style>
    <h3>Highlight residues</h3>
    <label class="e3-highlight-target" hidden>Structure to highlight
      <select aria-label="Structure to highlight"><option value="reference">Reference</option><option value="mobile">Aligned member</option></select>
    </label>
    <label>Protein domain <select class="e3-domain" aria-label="Protein domain"></select></label>
    <label class="trace-colour-picker">Domain colour <input type="color" value="${c}"></label>
    <p class="e3-domain-source" aria-live="polite"></p>`,H.before(n);let s=n.querySelector(".e3-highlight-target select");s.parentElement.hidden=!r;let p=n.querySelector(".e3-domain"),u=n.querySelector('input[type="color"]'),a=n.querySelector(".e3-domain-source"),w=O(n,l=>{e=l,x=B(l.ranges),draw()});function v(){return r?s.value:currentProtein().accession}function T(){let l=i[p.value];y=l?B(l.locations.flatMap(o=>o.fragments)):new Set,u.disabled=!l,a.textContent=l?.provenance==="recorded_coordinates"?"Recorded accession and length match. The domain overlay is approximate.":i.length?"":"Recorded domains are unavailable for this structure.",draw()}function S(){let l=h[v()];i=l?.features||[],p.replaceChildren(new Option("No domain selected",""));for(let[o,d]of i.entries()){let f=d.locations.flatMap(b=>b.fragments).map(({start:b,end:g})=>b===g?b:`${b}\u2013${g}`).join(", "),q=[d.accession,d.description,f].filter(Boolean).join(" \xB7 ");p.appendChild(new Option(q,String(o)))}p.disabled=!i.length,T(),w.setSequence(l?.sequence)}function k(l,o,d,f=!1){ctx.beginPath(),ctx.arc(l.x,l.y,o*devicePixelRatio,0,2*Math.PI),ctx.strokeStyle="#131c2b",ctx.lineWidth=4*devicePixelRatio,ctx.stroke(),ctx.strokeStyle=d,ctx.lineWidth=2.3*devicePixelRatio,f&&ctx.setLineDash([4*devicePixelRatio,2*devicePixelRatio]),ctx.stroke(),ctx.setLineDash([])}draw=function(){t();let o=0,d=0;if(y.size||x.size){let f=v(),q=new Set;ctx.save();for(let b of projected){if(r&&b.kind!==f)continue;let g=Number(b.atom.resi);q.has(g)||(q.add(g),y.has(g)&&(k(b,8.9,u.value,!0),o+=1),x.has(g)&&(k(b,y.has(g)?12:8.9,e.colour),d+=1))}ctx.restore()}canvas.dataset.domainCount=String(o),canvas.dataset.sequenceCount=String(d)};let $=r?"Pairwise superposition":"Published pocket-review model",R=document.getElementById("downloadViewPdf")||document.createElement("button");if(R.parentElement||(R.type="button",R.textContent="Download 3D view (PDF)",n.appendChild(R)),R.onclick=()=>{let{canvasPdf:l,downloadBlob:o,safePdfName:d}=globalThis.E3ViewerPdf,f=[];if(i[p.value]&&f.push({colour:u.value,label:`Domain: ${p.selectedOptions[0].textContent}`}),x.size){let g=e.regularExpression?"Regex ":"";f.push({colour:e.colour,label:`Matches: ${g}${e.query} \xB7 ${e.summary}`})}if(r&&typeof colours<"u")for(let g of["reference","mobile"]){let C=g==="reference"?"Reference":"Aligned member";document.getElementById(g==="reference"?"showReference":"showMobile").checked&&document.getElementById("showPocket").checked&&f.push({colour:colours[g+"Pocket"],label:`${C} pocket`})}else if(!r&&typeof palette<"u"){let g=selectedRank(),C=new Set(projected.flatMap(E=>(E.atom.pockets||[]).map(P=>P.selection_rank).filter(P=>!g||P===g)));for(let E of[...C].sort((P,L)=>P-L))f.push({colour:palette[E]||"#ffffff",label:`Pocket rank ${E}`})}let b=`${$} \xB7 ${v()}`;o(l({canvas,title:m,subtitle:b,legend:f,background:getComputedStyle(canvas).backgroundColor}),`${d(m+"_"+v())}_3d_view.pdf`)},s.addEventListener("change",S),p.addEventListener("change",T),u.addEventListener("input",draw),document.getElementById("proteinSelect")?.addEventListener("change",S),r)for(let l of["showReference","showMobile","showPocket"]){let o=document.getElementById(l);o&&(o.onchange=()=>draw())}S()}})();
