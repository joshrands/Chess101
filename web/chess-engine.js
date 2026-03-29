/**
 * Chess engine — extracted from sim.html <script id="chess-engine">.
 *
 * Contains all piece classes, board utilities, AI tree, and alpha-beta search.
 * No DOM or canvas dependencies. Runs in browser, Node.js, and Web Workers.
 */

'use strict';

// ── Data structures ──────────────────────────────────────────────────────────
class Cell{constructor(r,c){this.row=r;this.col=c;}}
class Team{constructor(r,g,b,name='Wendy'){this.r=r;this.g=g;this.b=b;this.name=name;}}

// ── Piece base ────────────────────────────────────────────────────────────────
class Piece{
  constructor(row,col,team){
    this.row=row;this.col=col;this.team=team;
    this.targets=[];this.critical=false;this.criticalTargets=[];this.touched=false;
  }
  getTargets(){return this.targets;}
  getValue(grid){return this.pieceValue;}
  _bladeRunner(grid,dr,dc,row,col){
    const nr=row+dr,nc=col+dc;
    if(nr<0||nr>7||nc<0||nc>7)return;
    const t=grid[nr][nc];
    if(t===null){this.targets.push(new Cell(nr,nc));this._bladeRunner(grid,dr,dc,nr,nc);}
    else if(t.team.r!==this.team.r)this.targets.push(new Cell(nr,nc));
  }
  _kingsman(grid,row,col,dr,dc){
    if(row<0||row>7||col<0||col>7)return[-1,-1];
    const p=grid[row][col];
    if(p!==null){return p.team.r!==this.team.r?[row,col]:[-1,-1];}
    const nr=row+dr,nc=col+dc;
    if(nr<0||nr>7||nc<0||nc>7)return[-1,-1];
    return this._kingsman(grid,nr,nc,dr,dc);
  }
  criticalMan(){
    if(!this.critical)return;
    const n=[];
    for(const ct of this.criticalTargets)
      for(const t of this.targets)
        if(ct.row===t.row&&ct.col===t.col){n.push(t);break;}
    this.targets=n;
  }
  skyFall(king){
    const n=[];
    for(const t of this.targets)
      for(const s of king.godSaveTheKing)
        if(t.row===s.row&&t.col===s.col){n.push(t);break;}
    this.targets=n;
  }
  move(newRow,newCol,grid){this.row=newRow;this.col=newCol;this.touched=true;return null;}
}

// ── Pawn ─────────────────────────────────────────────────────────────────────
class Pawn extends Piece{
  constructor(row,col,team){
    super(row,col,team);
    this.startingRow=row;this.startingCol=col;
    this.direction=row===6?-1:1; // BUG-01 preserved
    this.enPassantable=false;this.enPassantLoc=null;
    this.pieceValue=5;
  }
  calcTargets(grid){
    this.enPassantLoc=null;this.targets=[];
    if(this.row===0||this.row===7)return;
    const d=this.direction,r=this.row,c=this.col;
    // diagonal captures
    if(c>0){const p=grid[r+d][c-1];if(p&&p.team.r!==this.team.r)this.targets.push(new Cell(r+d,c-1));}
    if(c<7){const p=grid[r+d][c+1];if(p&&p.team.r!==this.team.r)this.targets.push(new Cell(r+d,c+1));}
    // forward
    if(grid[r+d][c]===null){
      this.targets.push(new Cell(r+d,c));
      if(r===this.startingRow&&grid[r+2*d][c]===null)this.targets.push(new Cell(r+2*d,c));
    }
    // en passant
    if(c>0){const n=grid[r][c-1];if(n instanceof Pawn&&n.team.r!==this.team.r&&n.enPassantable){this.targets.push(new Cell(r+d,c-1));this.enPassantLoc=new Cell(r+d,c-1);}}
    if(c<7){const n=grid[r][c+1];if(n instanceof Pawn&&n.team.r!==this.team.r&&n.enPassantable){this.targets.push(new Cell(r+d,c+1));this.enPassantLoc=new Cell(r+d,c+1);}}
    if(this.critical)super.criticalMan();
  }
  skyFall(king){
    const n=[];
    for(const t of this.targets)for(const s of king.godSaveTheKing)if(t.row===s.row&&t.col===s.col){n.push(t);break;}
    if(this.enPassantLoc!==null){
      const loc=this.enPassantLoc;
      const inPre=this.targets.some(t=>t.row===loc.row&&t.col===loc.col);
      const capturedRow=loc.row-this.direction;
      const capturesChecker=king.godSaveTheKing.some(s=>s.row===capturedRow&&s.col===loc.col);
      if(inPre&&capturesChecker)n.push(new Cell(loc.row,loc.col));
    }
    this.targets=n;
  }
  move(newRow,newCol,grid){
    const oldRow=this.row,oldCol=this.col;
    this.row=newRow;this.col=newCol;
    if(oldRow===this.startingRow&&oldCol===this.startingCol&&(newRow-oldRow)===2*this.direction)
      this.enPassantable=true;
    if(this.enPassantLoc!==null&&newRow===this.enPassantLoc.row&&newCol===this.enPassantLoc.col)
      return new Cell(this.enPassantLoc.row-this.direction,this.enPassantLoc.col);
    return null;
  }
  getValue(grid){
    this.calcTargets(grid);
    let v=this.pieceValue+this.targets.length;
    for(const c of this.targets){v++;if((c.row===3||c.row===4)&&(c.col===3||c.col===4))v++;}
    return v;
  }
}

// ── Rook ──────────────────────────────────────────────────────────────────────
class Rook extends Piece{
  constructor(row,col,team){super(row,col,team);this.pieceValue=27;}
  calcTargets(grid){
    this.targets=[];
    this._bladeRunner(grid,1,0,this.row,this.col);
    this._bladeRunner(grid,-1,0,this.row,this.col);
    this._bladeRunner(grid,0,1,this.row,this.col);
    this._bladeRunner(grid,0,-1,this.row,this.col);
    if(this.critical)super.criticalMan();
  }
  getValue(grid){
    this.calcTargets(grid);
    let v=this.pieceValue+this.targets.length;
    for(const c of this.targets)if((c.row===3||c.row===4)&&(c.col===3||c.col===4))v++;
    return v;
  }
}

// ── Bishop ────────────────────────────────────────────────────────────────────
class Bishop extends Piece{
  constructor(row,col,team){super(row,col,team);this.pieceValue=15;}
  calcTargets(grid){
    this.targets=[];
    this._bladeRunner(grid,1,1,this.row,this.col);
    this._bladeRunner(grid,1,-1,this.row,this.col);
    this._bladeRunner(grid,-1,1,this.row,this.col);
    this._bladeRunner(grid,-1,-1,this.row,this.col);
    if(this.critical)super.criticalMan();
  }
  getValue(grid){
    this.calcTargets(grid);
    let v=this.pieceValue+this.targets.length;
    for(const c of this.targets)if((c.row===3||c.row===4)&&(c.col===3||c.col===4))v++;
    return v;
  }
}

// ── Knight ────────────────────────────────────────────────────────────────────
class Knight extends Piece{
  constructor(row,col,team){super(row,col,team);this.pieceValue=13;}
  calcTargets(grid){
    this.targets=[];
    const offs=[[-2,-1],[-2,1],[-1,-2],[-1,2],[1,-2],[1,2],[2,-1],[2,1]];
    for(const[dr,dc]of offs){
      const nr=this.row+dr,nc=this.col+dc;
      if(nr<0||nr>7||nc<0||nc>7)continue;
      const p=grid[nr][nc];
      if(p===null||p.team.r!==this.team.r)this.targets.push(new Cell(nr,nc));
    }
    if(this.critical)super.criticalMan();
  }
  getValue(grid){
    this.calcTargets(grid);
    let v=this.pieceValue+this.targets.length;
    for(const c of this.targets)if((c.row===3||c.row===4)&&(c.col===3||c.col===4))v++;
    return v;
  }
}

// ── Queen ─────────────────────────────────────────────────────────────────────
class Queen extends Piece{
  constructor(row,col,team){super(row,col,team);this.pieceValue=49;}
  calcTargets(grid){
    this.targets=[];
    for(let dr=-1;dr<=1;dr++)for(let dc=-1;dc<=1;dc++)
      if(dr!==0||dc!==0)this._bladeRunner(grid,dr,dc,this.row,this.col);
    if(this.critical)super.criticalMan();
  }
  getValue(grid){
    this.calcTargets(grid);
    let v=this.pieceValue+this.targets.length;
    for(const c of this.targets)if((c.row===3||c.row===4)&&(c.col===3||c.col===4))v++;
    return v;
  }
}

// ── King ──────────────────────────────────────────────────────────────────────
class King extends Piece{
  constructor(row,col,team){
    super(row,col,team);
    this.direction=row===7?-1:1;
    this.godSaveTheKing=[];
    this.pieceValue=1000;
  }
  _bladeWalker(grid,dr,dc,row,col){
    const nr=row+dr,nc=col+dc;
    if(nr<0||nr>7||nc<0||nc>7)return;
    const p=grid[nr][nc];
    if(p===null||p.team.r!==this.team.r)this.targets.push(new Cell(nr,nc));
  }
  calcTargets(grid){
    this.targets=[];
    for(let dr=-1;dr<=1;dr++)for(let dc=-1;dc<=1;dc++)
      if(dr!==0||dc!==0)this._bladeWalker(grid,dr,dc,this.row,this.col);
    // Castling
    if(!this.touched){
      const lr=grid[this.row][this.col-4];
      if(lr instanceof Rook&&!lr.touched&&grid[this.row][this.col-1]===null&&grid[this.row][this.col-2]===null&&grid[this.row][this.col-3]===null)
        this.targets.push(new Cell(this.row,this.col-2));
      const rr=grid[this.row][this.col+3];
      if(rr instanceof Rook&&!rr.touched&&grid[this.row][this.col+1]===null&&grid[this.row][this.col+2]===null)
        this.targets.push(new Cell(this.row,this.col+2));
    }
    const oldRow=this.row,oldCol=this.col;
    let castleLeft=false,castleRight=false,castleLeftStep=true,castleRightStep=true;
    let castleLeftCell=null,castleRightCell=null;
    const toRemove=[];
    for(const cell of this.targets){
      if(cell.row===oldRow&&cell.col===oldCol-2){castleLeft=true;castleLeftCell=cell;}
      if(cell.row===oldRow&&cell.col===oldCol+2){castleRight=true;castleRightCell=cell;}
      const orig=grid[cell.row][cell.col];
      grid[cell.row][cell.col]=this;grid[this.row][this.col]=null;
      this.row=cell.row;this.col=cell.col;
      const[tr,tc]=this.amIGonnaDie(grid);
      if(tr!==-1){
        if(cell.row===oldRow&&cell.col===oldCol-2)castleLeft=false;
        if(cell.row===oldRow&&cell.col===oldCol+2)castleRight=false;
        if(cell.row===oldRow&&cell.col===oldCol-1)castleLeftStep=false;
        if(cell.row===oldRow&&cell.col===oldCol+1)castleRightStep=false;
        toRemove.push(cell);
      }
      grid[oldRow][oldCol]=this;grid[cell.row][cell.col]=orig;
      this.row=oldRow;this.col=oldCol;
    }
    const[ar,ac]=this.amIGonnaDie(grid);
    const inCheck=ar!==-1;
    if(castleLeft&&(inCheck||!castleLeftStep)&&castleLeftCell)toRemove.push(castleLeftCell);
    if(castleRight&&(inCheck||!castleRightStep)&&castleRightCell)toRemove.push(castleRightCell);
    for(const r of toRemove)this.targets=this.targets.filter(t=>!(t.row===r.row&&t.col===r.col));
    return inCheck;
  }
  move(newRow,newCol,grid){
    const oldRow=this.row,oldCol=this.col;
    this.row=newRow;this.col=newCol;this.touched=true;
    if(newRow===oldRow&&newCol===oldCol-2)return[new Cell(oldRow,oldCol-4),new Cell(oldRow,oldCol-1)];
    if(newRow===oldRow&&newCol===oldCol+2)return[new Cell(oldRow,oldCol+3),new Cell(oldRow,oldCol+1)];
    return[null,null];
  }
  getValue(grid){return this.pieceValue;}
  _iSpy(grid,row,col,dr,dc){
    if(row<0||row>7||col<0||col>7)return[-1,-1,-1,-1];
    const p=grid[row][col];
    const nr=row+dr,nc=col+dc,nextOk=nr>=0&&nr<=7&&nc>=0&&nc<=7;
    if(p!==null){
      if(p.team.r!==this.team.r)return[row,col,-1,-1];
      if(nextOk){const[sr,sc]=p._kingsman(grid,nr,nc,dr,dc);return[sr,sc,row,col];}
      return[-1,-1,-1,-1];
    }
    if(nextOk)return this._iSpy(grid,nr,nc,dr,dc);
    return[-1,-1,-1,-1];
  }
  _knightInShiningArmor(grid,dr,dc){
    const nr=this.row+dr,nc=this.col+dc;
    if(nr<0||nr>7||nc<0||nc>7)return[-1,-1];
    const p=grid[nr][nc];
    if(p instanceof Knight&&p.team.r!==this.team.r)return[nr,nc];
    return[-1,-1];
  }
  pleaseGodSaveTheKing(er,ec){
    const[dr,dc]=this._dirFromEnemy(er,ec);
    const cells=[];let r=er,c=ec;
    while(!(Math.round(r)===this.row&&Math.round(c)===this.col)){
      cells.push(new Cell(Math.round(r),Math.round(c)));r+=dr;c+=dc;
    }
    return cells;
  }
  _dirFromEnemy(er,ec){
    if(er===this.row)return[0,-(ec-this.col)/Math.abs(ec-this.col)];
    if(ec===this.col)return[-(er-this.row)/Math.abs(er-this.row),0];
    return[-(er-this.row)/Math.abs(er-this.row),-(ec-this.col)/Math.abs(ec-this.col)];
  }
  amIGonnaDie(grid){
    // Clear friendly critical flags
    for(const row of grid)for(const p of row)if(p&&p.team.r===this.team.r)p.critical=false;
    let ar=-1,ac=-1,attackerCount=0;
    for(let i=-1;i<=1;i++){
      for(let j=-1;j<=1;j++){
        if(i===0&&j===0)continue;
        const[er,ec,sr,sc]=this._iSpy(grid,this.row+i,this.col+j,i,j);
        const orthogonal=(i===0||j===0);
        if(sr!==-1){
          if(er!==-1){
            const ep=grid[er][ec];
            const typeOk=orthogonal?(ep instanceof Rook||ep instanceof Queen):(ep instanceof Bishop||ep instanceof Queen);
            if(typeOk){const sp=grid[sr][sc];if(sp){sp.critical=true;sp.criticalTargets=this.pleaseGodSaveTheKing(er,ec);}}
          }
        } else if(er!==-1){
          const ep=grid[er][ec];
          if(orthogonal){
            if(ep instanceof Rook||ep instanceof Queen){this.godSaveTheKing=this.pleaseGodSaveTheKing(er,ec);ar=er;ac=ec;attackerCount++;}
            else if(ep instanceof King&&Math.abs(er-this.row)+Math.abs(ec-this.col)===1){this.godSaveTheKing=this.pleaseGodSaveTheKing(er,ec);ar=er;ac=ec;attackerCount++;}
          } else {
            if(ep instanceof Bishop||ep instanceof Queen){this.godSaveTheKing=this.pleaseGodSaveTheKing(er,ec);ar=er;ac=ec;attackerCount++;}
            else if(ep instanceof King&&Math.abs(er-this.row)+Math.abs(ec-this.col)===2){this.godSaveTheKing=this.pleaseGodSaveTheKing(er,ec);ar=er;ac=ec;attackerCount++;}
            else if(ep instanceof Pawn&&(er-this.row)===this.direction){this.godSaveTheKing=this.pleaseGodSaveTheKing(er,ec);ar=er;ac=ec;attackerCount++;}
          }
        }
      }
    }
    // Knight checks
    for(const[dr,dc]of[[-2,-1],[-2,1],[-1,-2],[-1,2],[1,-2],[1,2],[2,-1],[2,1]]){
      const[kr,kc]=this._knightInShiningArmor(grid,dr,dc);
      if(kr!==-1){this.godSaveTheKing=[new Cell(kr,kc)];ar=kr;ac=kc;attackerCount++;break;}
    }
    // Double check: only king moves are legal — no piece can block/capture
    // two attackers at once.  Clear godSaveTheKing so skyFall filters all.
    if(attackerCount>1)this.godSaveTheKing=[];
    return[ar,ac];
  }
}

// ── Board copy ────────────────────────────────────────────────────────────────
function copyPiece(p,teamR,teamL){
  const team=p.team.r===teamR.r?teamR:teamL;
  let c;
  if(p instanceof Pawn){c=new Pawn(p.row,p.col,team);c.startingRow=p.startingRow;c.startingCol=p.startingCol;c.direction=p.direction;c.enPassantable=p.enPassantable;c.enPassantLoc=p.enPassantLoc?new Cell(p.enPassantLoc.row,p.enPassantLoc.col):null;}
  else if(p instanceof King){c=new King(p.row,p.col,team);c.direction=p.direction;}
  else if(p instanceof Queen)c=new Queen(p.row,p.col,team);
  else if(p instanceof Rook)c=new Rook(p.row,p.col,team);
  else if(p instanceof Bishop)c=new Bishop(p.row,p.col,team);
  else c=new Knight(p.row,p.col,team);
  c.touched=p.touched;c.critical=p.critical;c.criticalTargets=[];c.targets=[];
  return c;
}
function deepCopyGrid(grid,teamR,teamL){
  return grid.map(row=>row.map(p=>p?copyPiece(p,teamR,teamL):null));
}

// ── Serialization (for Worker postMessage) ────────────────────────────────────
function serializeGrid(grid){
  return grid.map(row=>row.map(p=>{
    if(!p)return null;
    const t={type:p.constructor.name,row:p.row,col:p.col,tr:p.team.r,tg:p.team.g,tb:p.team.b,touched:p.touched};
    if(p instanceof Pawn){t.startingRow=p.startingRow;t.direction=p.direction;t.enPassantable=p.enPassantable;t.enPassantLoc=p.enPassantLoc?{row:p.enPassantLoc.row,col:p.enPassantLoc.col}:null;}
    if(p instanceof King){t.direction=p.direction;}
    return t;
  }));
}
function deserializeGrid(data,teamR,teamL){
  return data.map(row=>row.map(p=>{
    if(!p)return null;
    const team=p.tr===teamR.r?teamR:teamL;
    let c;
    if(p.type==='Pawn'){c=new Pawn(p.row,p.col,team);c.startingRow=p.startingRow;c.direction=p.direction;c.enPassantable=p.enPassantable;c.enPassantLoc=p.enPassantLoc?new Cell(p.enPassantLoc.row,p.enPassantLoc.col):null;}
    else if(p.type==='King'){c=new King(p.row,p.col,team);if(p.direction!==undefined)c.direction=p.direction;}
    else if(p.type==='Queen')c=new Queen(p.row,p.col,team);
    else if(p.type==='Rook')c=new Rook(p.row,p.col,team);
    else if(p.type==='Bishop')c=new Bishop(p.row,p.col,team);
    else c=new Knight(p.row,p.col,team);
    c.touched=p.touched;c.critical=false;c.criticalTargets=[];c.targets=[];
    return c;
  }));
}

// ── AI tree node ──────────────────────────────────────────────────────────────
class TreeNode{
  constructor(board,oldCell,newCell,teamR,teamL){
    this.boardState=board;this.oldCell=oldCell;this.newCell=newCell;
    this.teamR=new Team(teamR.r,teamR.g,teamR.b);this.teamL=new Team(teamL.r,teamL.g,teamL.b);
    this.children=[];
  }
  addChild(c){this.children.push(c);}
  getUtility(team){
    let wr=0,wl=0;
    for(const row of this.boardState)for(const p of row){
      if(!p)continue;
      if(p.team.r===this.teamR.r)wr+=p.getValue(this.boardState);
      else wl+=p.getValue(this.boardState);
    }
    let total=wr-wl;
    if(team.r===this.teamL.r)total=-total;
    return total;
  }
}

// ── Alpha-beta search ─────────────────────────────────────────────────────────
function alphaBetaSearch(root,team){
  let bestVal=-Infinity,beta=Infinity,best=null;
  for(const s of root.children){
    const v=abMin(s,bestVal,beta,team);
    if(v>bestVal){bestVal=v;best=s;}
  }
  return best;
}
function abMax(node,alpha,beta,team){
  if(!node.children.length)return node.getUtility(team);
  let v=-Infinity;
  for(const s of node.children){v=Math.max(v,abMin(s,alpha,beta,team));if(v>=beta)return v;alpha=Math.max(alpha,v);}
  return v;
}
function abMin(node,alpha,beta,team){
  if(!node.children.length)return node.getUtility(team);
  let v=Infinity;
  for(const s of node.children){v=Math.min(v,abMax(s,alpha,beta,team));if(v<=alpha)return v;beta=Math.min(beta,v);}
  return v;
}

// ── Tree builder (used inside Worker) ────────────────────────────────────────
function addNodes(node,teamR,teamL,team,depth){
  if(depth===0)return;
  const board=node.boardState;
  const pieces=[];for(const row of board)for(const p of row)if(p&&p.team.r===team.r)pieces.push(p);
  let king=null,check=false;
  for(const p of pieces)if(p instanceof King){king=p;check=p.calcTargets(board);}
  for(const p of pieces){
    p.calcTargets(board);
    if(check&&!(p instanceof King))p.skyFall(king);
    for(const target of p.targets){
      const nb=deepCopyGrid(board,teamR,teamL);
      const np=nb[p.row][p.col];
      nb[target.row][target.col]=np;
      if(np instanceof Pawn){
        const enemy=np.move(target.row,target.col,nb);
        if(enemy)nb[enemy.row][enemy.col]=null;
        // auto-promote
        if((np.startingRow+6)%12===target.row)nb[target.row][target.col]=new Queen(target.row,target.col,np.team);
      } else if(np instanceof King){
        const[rl,rt]=np.move(target.row,target.col,nb);
        if(rl&&rt){nb[rt.row][rt.col]=nb[rl.row][rl.col];nb[rl.row][rl.col]=null;const rp=nb[rt.row][rt.col];if(rp)rp.move(rt.row,rt.col,nb);}
      } else {np.move(target.row,target.col,nb);}
      nb[p.row][p.col]=null;
      const child=new TreeNode(nb,new Cell(p.row,p.col),new Cell(target.row,target.col),teamR,teamL);
      node.addChild(child);
    }
  }
  const next=team.r===teamL.r?teamR:teamL;
  for(const child of node.children)addNodes(child,teamR,teamL,next,depth-1);
}

// ── Worker entry point (runs only inside Worker context) ──────────────────────
if(typeof self!=='undefined'&&typeof document==='undefined'&&typeof module==='undefined'){
  self.onmessage=function(e){
    const d=e.data;
    const tR=new Team(d.teamR.r,d.teamR.g,d.teamR.b,d.teamR.name);
    const tL=new Team(d.teamL.r,d.teamL.g,d.teamL.b,d.teamL.name);
    const grid=deserializeGrid(d.grid,tR,tL);
    const currentTeam=d.currentTeamIsR?tR:tL;
    const root=new TreeNode(grid,null,null,tR,tL);
    addNodes(root,tR,tL,currentTeam,d.depth);
    const best=alphaBetaSearch(root,currentTeam);
    if(best)self.postMessage({fromRow:best.oldCell.row,fromCol:best.oldCell.col,toRow:best.newCell.row,toCol:best.newCell.col});
    else self.postMessage(null);
  };
}

// ── Node.js exports ──────────────────────────────────────────────────────────
if(typeof module!=='undefined'&&module.exports){
  module.exports={
    Cell,Team,Piece,Pawn,Rook,Bishop,Knight,Queen,King,
    copyPiece,deepCopyGrid,serializeGrid,deserializeGrid,
    TreeNode,alphaBetaSearch,abMax,abMin,addNodes,
  };
}
