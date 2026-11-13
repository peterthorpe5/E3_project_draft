(()=>{var B="#e32860";function W({sequence:w,query:h}){let n=h.replace(/\s/g,"");if(!n)return[];if(!/^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$/i.test(n))throw new Error("Use amino-acid letters, for example QWFAA.");let d=n.toUpperCase(),i=[];for(let m=w.indexOf(d);m!==-1;m=w.indexOf(d,m+1))i.push({start:m+1,end:m+d.length});return i}function z(w){let h=[];for(let{start:n,end:d}of w){let i=h.at(-1);i&&n<=i.end+1?i.end=Math.max(i.end,d):h.push({start:n,end:d})}return h}function L(w){let h=new Set;for(let{start:n,end:d}of w)for(let i=n;i<=d;i+=1)h.add(i);return h}function O(w,h){let n=document.createElement("section");n.className="sequence-search",n.innerHTML=`
    <form>
      <label>Amino-acid sequence
        <input type="text" placeholder="e.g. QWFAA" spellcheck="false" autocomplete="off">
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
        <input type="color" value="${B}">
      </label>
    </div>
    <p role="status" aria-live="polite"></p>`,w.appendChild(n);let d=n.querySelector("form"),i=d.querySelector("input"),m=d.querySelector('button[type="submit"]'),v=d.querySelector('button[type="button"]'),x=n.querySelector("select"),e=n.querySelector('input[type="number"]'),o=n.querySelector('input[type="color"]'),c=n.querySelector("p"),r="",t=[],p=!1,E="",S="";function C(){let l=x.value==="one",y=Math.min(Math.max(1,Math.trunc(Number(e.value))||1),t.length);y&&(e.value=String(y)),e.max=String(t.length),e.parentElement.hidden=!l||!t.length,x.disabled=t.length<2,i.disabled=m.disabled=!r,v.disabled=!p&&!i.value;let a=l?t.slice(y-1,y):t,b=a.slice(0,8).map(({start:$,end:u})=>$===u?String($):`${$}\u2013${u}`).join(", ")+(a.length>8?", \u2026":""),f=l&&t.length>1?`Match ${y} of ${t.length}`:`${t.length} ${t.length===1?"match":"matches"}`;c.textContent=r?E||(t.length?`${f} \xB7 ${b}`:p?"No exact matches.":""):"A verified sequence is unavailable for this structure.",h({ranges:z(a),colour:o.value,summary:c.textContent,query:S})}function R(){p=!!i.value.trim(),t=[],E="",S=i.value.replace(/\s/g,"").toUpperCase(),e.value="1";try{t=W({sequence:r,query:i.value})}catch(l){E=l.message}t.length<2&&(x.value="all"),C()}d.addEventListener("submit",l=>{l.preventDefault(),R()}),i.addEventListener("input",()=>{v.disabled=!p&&!i.value});for(let l of[x,e,o])l.addEventListener("change",C);o.addEventListener("input",C);function P(){i.value="",x.value="all",R()}return v.addEventListener("click",P),{setSequence(l){r=l||"",i.maxLength=Math.max(1,r.length+100),R()},clear:P,resetColour(){o.value=B,C()},get colourChanged(){return o.value!==B}}}(()=>{let w=new TextEncoder,h=e=>typeof e=="string"?w.encode(e):e;function n(e){let o=e.map(h),c=new Uint8Array(o.reduce((t,p)=>t+p.length,0)),r=0;for(let t of o)c.set(t,r),r+=t.length;return c}function d(e){let o=[h(`%PDF-1.4
`)],c=[0],r=o[0].length;for(let[p,E]of e.entries()){c.push(r);let S=n([`${p+1} 0 obj
`,E,`
endobj
`]);o.push(S),r+=S.length}let t=`xref
0 ${e.length+1}
0000000000 65535 f 
`;for(let p of c.slice(1))t+=`${String(p).padStart(10,"0")} 00000 n 
`;return o.push(h(t+`trailer
<< /Size ${e.length+1} /Root 1 0 R >>
startxref
${r}
%%EOF
`)),new Blob(o,{type:"application/pdf"})}function i(e,o){let c=document.createElement("a");c.href=URL.createObjectURL(e),c.download=o,c.click(),setTimeout(()=>URL.revokeObjectURL(c.href),1e3)}function m(e){return String(e||"protein").replace(/[^A-Za-z0-9_.-]+/g,"_").slice(0,140)}function v(e){return String(e).replace(/[–—]/g,"-").replace(/·/g,"|").replace(/α/g,"alpha").replace(/[^\x20-\x7E]/g,"?").replace(/([\\()])/g,"\\$1")}function x({canvas:e,title:o,subtitle:c="",legend:r=[],background:t="#fff"}){if(!e.width||!e.height)throw new Error("The structure view is empty.");let p=document.createElement("canvas");p.width=e.width,p.height=e.height;let E=p.getContext("2d");E.fillStyle=t,E.fillRect(0,0,e.width,e.height),E.drawImage(e,0,0);let S=p.toDataURL("image/jpeg",.97).split(",")[1],C=Uint8Array.from(atob(S),k=>k.charCodeAt(0)),R=842,P=595,l=25,y=r.slice(0,16),a=Math.ceil(y.length/2),s=l+a*17+(a?10:0),b=P-(c?70:54),f=Math.min((R-2*l)/e.width,(b-s)/e.height),$=e.width*f,u=e.height*f,g=(R-$)/2,M=s+(b-s-u)/2,T=[`q ${$.toFixed(2)} 0 0 ${u.toFixed(2)} ${g.toFixed(2)} ${M.toFixed(2)} cm /Im0 Do Q`,`BT /F1 16 Tf ${l} 560 Td (${v(String(o).slice(0,86))}) Tj ET`];c&&T.push(`BT /F1 10 Tf ${l} 542 Td (${v(String(c).slice(0,126))}) Tj ET`),y.forEach(({colour:k,label:N},D)=>{let F=l+D%2*397,j=s-16-Math.floor(D/2)*17,_=/^#[\da-f]{6}$/i.test(k)?k.slice(1):"243246",Q=[0,2,4].map(A=>(parseInt(_.slice(A,A+2),16)/255).toFixed(3)).join(" ");T.push(`q ${Q} rg 0.14 0.20 0.28 RG ${F} ${j-1} 9 9 re B Q`,`BT /F1 10 Tf ${F+15} ${j} Td (${v(String(N).slice(0,72))}) Tj ET`)});let q=T.join(`
`);return d(["<< /Type /Catalog /Pages 2 0 R >>","<< /Type /Pages /Kids [3 0 R] /Count 1 >>",`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${R} ${P}] /Resources << /XObject << /Im0 4 0 R >> /Font << /F1 6 0 R >> >> /Contents 5 0 R >>`,n([`<< /Type /XObject /Subtype /Image /Width ${e.width} /Height ${e.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${C.length} >>
stream
`,C,`
endstream`]),`<< /Length ${h(q).length} >>
stream
${q}
endstream`,"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"])}globalThis.E3ViewerPdf={buildPdf:d,downloadBlob:i,safePdfName:m,pdfText:v,canvasPdf:x}})();var U=document.getElementById("e3ReviewHighlights"),H=document.getElementById("e3TerminalTrimControls");U&&H&&typeof draw=="function"&&typeof canvas<"u"&&V();function V(){let{group:w,targets:h}=JSON.parse(U.textContent),n=!!document.getElementById("alignmentData"),d="#c1a8ff",i=draw,m=[],v=new Set,x=new Set,e,o=document.createElement("section");o.className="e3-review-highlights",o.setAttribute("aria-label","Highlight domains and sequence matches"),o.innerHTML=`
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
    <label class="trace-colour-picker">Domain colour <input type="color" value="${d}"></label>
    <p class="e3-domain-source" aria-live="polite"></p>`,H.before(o);let c=o.querySelector(".e3-highlight-target select");c.parentElement.hidden=!n;let r=o.querySelector(".e3-domain"),t=o.querySelector('input[type="color"]'),p=o.querySelector(".e3-domain-source"),E=O(o,a=>{e=a,v=L(a.ranges),draw()});function S(){return n?c.value:currentProtein().accession}function C(){let a=m[r.value];x=a?L(a.locations.flatMap(s=>s.fragments)):new Set,t.disabled=!a,p.textContent=a?.provenance==="recorded_coordinates"?"Recorded accession and length match. The domain overlay is approximate.":m.length?"":"Recorded domains are unavailable for this structure.",draw()}function R(){let a=h[S()];m=a?.features||[],r.replaceChildren(new Option("No domain selected",""));for(let[s,b]of m.entries()){let f=b.locations.flatMap(u=>u.fragments).map(({start:u,end:g})=>u===g?u:`${u}\u2013${g}`).join(", "),$=[b.accession,b.description,f].filter(Boolean).join(" \xB7 ");r.appendChild(new Option($,String(s)))}r.disabled=!m.length,C(),E.setSequence(a?.sequence)}function P(a,s,b,f=!1){ctx.beginPath(),ctx.arc(a.x,a.y,s*devicePixelRatio,0,2*Math.PI),ctx.strokeStyle="#131c2b",ctx.lineWidth=4*devicePixelRatio,ctx.stroke(),ctx.strokeStyle=b,ctx.lineWidth=2.3*devicePixelRatio,f&&ctx.setLineDash([4*devicePixelRatio,2*devicePixelRatio]),ctx.stroke(),ctx.setLineDash([])}draw=function(){i();let s=0,b=0;if(x.size||v.size){let f=S(),$=new Set;ctx.save();for(let u of projected){if(n&&u.kind!==f)continue;let g=Number(u.atom.resi);$.has(g)||($.add(g),x.has(g)&&(P(u,8.9,t.value,!0),s+=1),v.has(g)&&(P(u,x.has(g)?12:8.9,e.colour),b+=1))}ctx.restore()}canvas.dataset.domainCount=String(s),canvas.dataset.sequenceCount=String(b)};let l=n?"Pairwise superposition":"Published pocket-review model",y=document.getElementById("downloadViewPdf")||document.createElement("button");if(y.parentElement||(y.type="button",y.textContent="Download 3D view (PDF)",o.appendChild(y)),y.onclick=()=>{let{canvasPdf:a,downloadBlob:s,safePdfName:b}=globalThis.E3ViewerPdf,f=[];if(m[r.value]&&f.push({colour:t.value,label:`Domain: ${r.selectedOptions[0].textContent}`}),v.size&&f.push({colour:e.colour,label:`Matches: ${e.query} \xB7 ${e.summary}`}),n&&typeof colours<"u")for(let g of["reference","mobile"]){let M=g==="reference"?"Reference":"Aligned member";document.getElementById(g==="reference"?"showReference":"showMobile").checked&&document.getElementById("showPocket").checked&&f.push({colour:colours[g+"Pocket"],label:`${M} pocket`})}else if(!n&&typeof palette<"u"){let g=selectedRank(),M=new Set(projected.flatMap(T=>(T.atom.pockets||[]).map(q=>q.selection_rank).filter(q=>!g||q===g)));for(let T of[...M].sort((q,k)=>q-k))f.push({colour:palette[T]||"#ffffff",label:`Pocket rank ${T}`})}let u=`${l} \xB7 ${S()}`;s(a({canvas,title:w,subtitle:u,legend:f,background:getComputedStyle(canvas).backgroundColor}),`${b(w+"_"+S())}_3d_view.pdf`)},c.addEventListener("change",R),r.addEventListener("change",C),t.addEventListener("input",draw),document.getElementById("proteinSelect")?.addEventListener("change",R),n)for(let a of["showReference","showMobile","showPocket"]){let s=document.getElementById(a);s&&(s.onchange=()=>draw())}R()}})();
