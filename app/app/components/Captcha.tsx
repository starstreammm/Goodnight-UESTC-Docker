import { useRef, useState, type PointerEvent } from 'react'
import { Box, Button, Stack, Typography } from '@mui/material'
import {useLanguage} from '../i18n'
import { ArrowForward } from '@mui/icons-material'

export type Challenge = {
  ticket: string; image: string; width: number; height: number; image_height?: number; image_width?: number
  handle: {x:number; y:number; width:number; height:number}
  piece: null | {image:string; x:number; y:number; width:number; height:number}
}
export type Point = {x:number; y:number; t:number}

export default function Captcha({challenge, disabled, onDrag, onRefresh}: {
  challenge: Challenge; disabled: boolean
  onDrag: (ticket:string, points:Point[]) => void; onRefresh: () => void
}) {
  const {t}=useLanguage()
  const gesture = useRef<{pointer:number; start:number; points:Point[]; box:DOMRect}|null>(null)
  const [offset, setOffset] = useState(0)
  const [hint, setHint] = useState(0)
  function point(e: PointerEvent, box: DOMRect, t: number): Point {
    return {x:Math.max(0, Math.min(1, (e.clientX-box.left)/box.width)),
      y:Math.max(0, Math.min(1, (e.clientY-box.top)/box.height)), t:Math.round(t)}
  }
  function down(e: PointerEvent<HTMLDivElement>) {
    if (disabled || gesture.current || e.button !== 0) return
    const box = e.currentTarget.getBoundingClientRect(), p = point(e,box,0), h = challenge.handle
    if (p.x < h.x || p.x > h.x+h.width || p.y < h.y || p.y > h.y+h.height) return
    e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId)
    gesture.current = {pointer:e.pointerId, start:performance.now(), points:[p], box}
    setOffset(0); setHint(1)
  }
  function move(e: PointerEvent<HTMLDivElement>) {
    const g = gesture.current
    if (!g || g.pointer !== e.pointerId) return
    const p = point(e,g.box,performance.now()-g.start), last = g.points[g.points.length-1]
    // Bound memory and request size; preserve the user's positions and timestamps.
    if (p.t-last.t >= 50 && g.points.length < 298) g.points.push(p)
    setOffset(p.x-g.points[0].x)
  }
  function up(e: PointerEvent<HTMLDivElement>) {
    const g = gesture.current
    if (!g || g.pointer !== e.pointerId) return
    gesture.current = null
    e.currentTarget.releasePointerCapture(e.pointerId)
    const last = point(e,g.box,performance.now()-g.start)
    if (last.t < 50 || last.t > 15000 || Math.abs(last.x-g.points[0].x) < .005) {
      setOffset(0); setHint(2); return
    }
    onDrag(challenge.ticket, [...g.points,last])
    setOffset(0)
  }
  const h = challenge.handle, piece = challenge.piece
  const shift = Math.max(0, Math.min(offset, 1-h.x-h.width))
  return <Stack spacing={1.5}>
    <Typography fontWeight={600}>{t('School CAPTCHA','学校验证码')}</Typography>
    <Typography variant="body2" color="text.secondary">{[t('Drag the handle until the puzzle piece fits, then release.','拖动滑块，使拼图吻合后松开。'),t('Release when the piece fits. Your drag will be sent to the school.','拼图吻合后松开，将由学校验证。'),t('Drag the slider again, taking less than 15 seconds.','请在 15 秒内重新拖动滑块。')][hint]}</Typography>
    <Box role="group" aria-label={t('School CAPTCHA puzzle','学校拼图验证码')} onPointerDown={down} onPointerMove={move} onPointerUp={up}
      onPointerCancel={() => {gesture.current=null; setOffset(0)}}
      onLostPointerCapture={() => {if (gesture.current) {gesture.current=null; setOffset(0)}}}
      sx={{position:'relative',aspectRatio:`${challenge.width}/${challenge.height}`,backgroundColor:'action.hover',width:'100%',maxWidth:challenge.width,alignSelf:'center',overflow:'hidden',touchAction:'none',userSelect:'none',opacity:disabled ? .65 : 1}}>
      <Box component="img" src={challenge.image} alt={t('School slider CAPTCHA','学校滑块验证码')} draggable={false} sx={{display:'block',width:`${(challenge.image_width ?? 1)*100}%`,height:`${(challenge.image_height ?? 1)*100}%`,pointerEvents:'none'}}/>
      {piece && <Box component="img" src={piece.image} alt="" draggable={false} sx={{position:'absolute',pointerEvents:'none',left:`${(piece.x+shift)*100}%`,top:`${piece.y*100}%`,width:`${piece.width*100}%`,height:`${piece.height*100}%`}}/>}
      <Box sx={{position:'absolute',left:`${(h.x+shift)*100}%`,top:`${h.y*100}%`,width:`${h.width*100}%`,height:`${h.height*100}%`,display:'grid',placeItems:'center',backgroundColor:'primary.main',color:'primary.contrastText',borderRadius:.5,cursor:disabled?'wait':'grab'}}><ArrowForward fontSize="small"/></Box>
    </Box>
    <Button disabled={disabled} onClick={onRefresh}>{t('Refresh CAPTCHA','刷新验证码')}</Button>
  </Stack>
}
