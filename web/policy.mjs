export function decide(g){
 if(g.override==='exclude')return {status:'Excluded',reason:'Your explicit exclusion'};
 if(g.override==='include')return {status:'Included',reason:'Your explicit exception'};
 if(g.curated)return {status:'Included',reason:'Protected by your curated Saves collection'};
 if(g.cloud==='working')return {status:'Excluded',reason:'Working Steam Cloud on this installation'};
 if(g.cloud==='none')return {status:'Included',reason:'No working Steam Cloud on this installation'};
 return {status:'Review',reason:'Confirm cloud coverage for this installed copy'};
}
