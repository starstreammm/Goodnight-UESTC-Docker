import { useState } from 'react'
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Slider, Stack, TextField, Typography } from '@mui/material'
import { api } from '../api'
import { errorText, useLanguage } from '../i18n'

export type AccountSettings = { id: number; alias: string; save_password: boolean; checkin_time: string | null; school_window: string | null }

function minutes(time: string) {
  const [hour, minute] = time.split(':').map(Number)
  return hour * 60 + minute
}

function time(value: number) {
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}

function initialRange(account: AccountSettings): number[] | null {
  if (!account.school_window) return null
  const available = account.school_window.split('_').map(minutes)
  if (!account.checkin_time) return available
  const saved = account.checkin_time.split('_').map(minutes)
  const start = Math.max(available[0], saved[0]), end = Math.min(available[1], saved[1])
  return start < end ? [start, end] : available
}

export default function SettingsDialog({ account, onClose, onSuccess, onLocation }: {
  account: AccountSettings; onClose: () => void; onSuccess: () => Promise<void>; onLocation: () => void
}) {
  const { t, language } = useLanguage()
  const [alias, setAlias] = useState(account.alias)
  const [range, setRange] = useState(() => initialRange(account))
  const [savePassword, setSavePassword] = useState(account.save_password)
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const available = account.school_window?.split('_').map(minutes)
  const adjusted = !!account.checkin_time && !!range && initialRange(account)?.map(time).join('_') !== account.checkin_time

  async function action(fn: () => Promise<void>) {
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(errorText(e, language)) } finally { setBusy(false) }
  }

  return <Dialog open onClose={() => !busy && onClose()} fullWidth maxWidth="sm">
    <DialogTitle>{t('Account settings', '账号设置')}</DialogTitle>
    <DialogContent><Stack spacing={2.5} mt={1}>
      {error && <Alert severity="error">{error}</Alert>}
      <TextField label={t('Alias', '别名')} value={alias} disabled={busy} inputProps={{ maxLength: 80 }} onChange={e => setAlias(e.target.value)} />
      <Box>
        <Typography id="checkin-range-label" variant="subtitle2">{t('Random check-in range', '随机签到时段')}</Typography>
        {available && range ? <>
          <Stack direction="row" justifyContent="space-between" alignItems="baseline" sx={{ gap: 1, flexWrap: 'wrap', mt: 0.5 }}>
            <Typography variant="h6" sx={{ fontVariantNumeric: 'tabular-nums' }}>{time(range[0])} – {time(range[1])}</Typography>
            <Typography variant="caption" color="text.secondary">{t('School accepts', '学校允许')} {time(available[0])} – {time(available[1] + 5)}</Typography>
          </Stack>
          <Box sx={{ px: 1.25, pt: 1 }}>
            <Slider value={range} min={available[0]} max={available[1]} step={1} disableSwap disabled={busy}
              getAriaLabel={index => index === 0 ? t('Earliest check-in time', '最早签到时间') : t('Latest check-in time', '最晚签到时间')}
              getAriaValueText={time} valueLabelFormat={time} valueLabelDisplay="auto"
              onChange={(_, value, thumb) => {
                const next = value as number[]
                setRange(thumb === 0 ? [Math.min(next[0], range[1] - 1), range[1]] : [range[0], Math.max(next[1], range[0] + 1)])
              }} />
            <Stack direction="row" justifyContent="space-between" sx={{ mt: -0.5 }}>
              <Typography variant="caption" color="text.secondary">{time(available[0])}</Typography>
              <Typography variant="caption" color="text.secondary">{time(available[1])}</Typography>
            </Stack>
          </Box>
          <Typography variant="body2" color="text.secondary" mt={1.5}>{t('A time is picked randomly within this range each day. Saving updates pending check-ins.', '每天在此时段内随机安排签到。保存后将更新尚未执行的签到计划。')}</Typography>
          <Typography variant="caption" color="text.secondary" display="block" mt={0.5}>{t('Shanghai time. The school window’s final 5 minutes are reserved to avoid late submissions.', '北京时间。预留学校签到时段的最后 5 分钟，避免超时提交。')}</Typography>
          {adjusted && <Alert severity="info" sx={{ mt: 1.5 }}>{t('Your saved range no longer fits today’s school hours. Save to use the range shown above.', '已保存的时段不完全符合今日学校安排。保存后将使用上方显示的时段。')}</Alert>}
        </> : <Alert severity="info" sx={{ mt: 1 }}>{t('Today’s school hours are not available yet. Reopen settings after the school schedule refreshes to choose a range.', '暂未获取今日学校签到时段。学校安排更新后，请重新打开设置选择时段。')}{account.checkin_time && <Typography variant="body2" mt={0.5}>{t('Saved range', '已保存时段')}: {account.checkin_time.replace('_', ' – ')}</Typography>}</Alert>}
      </Box>
      <Button variant="outlined" disabled={busy} onClick={onLocation}>{t('Choose check-in location', '选择签到位置')}</Button>
      {savePassword && <Button color="warning" disabled={busy} onClick={() => void action(async () => {
        await api(`/accounts/${account.id}/password`, 'DELETE'); setSavePassword(false); await onSuccess()
      })}>{t('Forget saved password', '删除已保存密码')}</Button>}
      <Typography variant="body2" color="text.secondary">{t('To save a new password, use Sign in again.', '如需保存新密码，请使用“重新登录”。')}</Typography>
    </Stack></DialogContent>
    <DialogActions>
      <Button disabled={busy} onClick={onClose}>{t('Cancel', '取消')}</Button>
      <Button variant="contained" disabled={busy || !alias.trim()} onClick={() => void action(async () => {
        await api(`/accounts/${account.id}`, 'PATCH', { alias, ...(range ? { checkin_time: range.map(time).join('_') } : {}) })
        await onSuccess(); onClose()
      })}>{t('Save', '保存')}</Button>
    </DialogActions>
  </Dialog>
}
