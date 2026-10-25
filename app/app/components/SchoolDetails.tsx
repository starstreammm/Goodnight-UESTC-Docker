import { Box, Divider, Stack, Typography } from '@mui/material'
import { useLanguage } from '../i18n'

export type SchoolSchedule = { date?: string; response?: { data?: Record<string, unknown> | null } }

export default function SchoolDetails({ detail, schedule, locationName }: { detail: Record<string, unknown>; schedule?: SchoolSchedule; locationName?: string | null }) {
  const { t } = useLanguage()
  const data = schedule?.response?.data

  function time(value: unknown) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return t('Not available', '暂无信息')
    const minutes = Math.round(value), days = Math.floor(minutes / 1440)
    return `${String(Math.floor(minutes / 60) % 24).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}${days ? ` (+${days} ${t('day', '天')})` : ''}`
  }

  const names: Record<string, string> = { realName: t('Real name', '姓名'), userName: t('Name', '姓名'), studentName: t('Name', '姓名'), studentId: t('Student ID', '学号'), collegeName: t('College', '学院'), majorName: t('Major', '专业') }

  return (
    <Stack spacing={0.75}>
      {Object.entries(detail).filter(([, value]) => value !== null).map(([key, value]) => <Box key={key} sx={{ display: 'grid', gridTemplateColumns: 'minmax(90px, 1fr) minmax(0, 2fr)', gap: 1, py: 0.25, alignItems: 'baseline' }}>
        <Typography variant="caption" color="text.secondary">{names[key] || key}</Typography>
        <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</Typography>
      </Box>)}
      <Divider />
      <Box><Typography variant="subtitle2">{t('School check-in schedule', '学校签到安排')}</Typography>
        <Typography>{data ? `${time(data.studentCheckinStartOffsetMinute)} – ${time(data.studentCheckinEndOffsetMinute)}` : t('No effective schedule returned by the school.', '学校尚未返回有效签到安排。')}</Typography>
        <Typography variant="caption" color="text.secondary">{schedule?.date} · Asia/Shanghai</Typography>
      </Box>
      {locationName && <Box><Typography variant="subtitle2">{t('Check-in location', '签到位置')}</Typography><Typography>{locationName}</Typography></Box>}
    </Stack>
  );
}
