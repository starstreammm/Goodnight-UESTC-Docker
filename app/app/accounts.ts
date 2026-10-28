import type { User } from "./auth";
import type { AccountSettings } from "./components/SettingsDialog";
import type { SchoolSchedule } from "./components/SchoolDetails";

export type Account = AccountSettings & {
    id: number;
    username: string;
    alias: string;
    real_name: string | null;
    status: string;
    location_name: string | null;
    save_password: boolean;
    uestc_expires_at: number | null;
    wechat_ref: string | null;
    owner_id: number;
    owner_username: string;
    owner_display_name: string;
    owner_role: "admin" | "user";
    owner_builtin: number;
};
type Job = {
    account_id: number;
    status: string;
    message: string | null;
    scheduled_at: string;
    checked_at: string | null;
    checked: number;
};
export type State = {
    user: User;
    accounts: Account[];
    jobs: Job[];
    busy_accounts: number[];
    date: string;
};
export type Info = {
    detail: Record<string, unknown>;
    schedule: SchoolSchedule;
    location_name: string | null;
    uestc_expires_at: number | null;
    save_password: boolean;
    wechat: {
        nickname: string;
        credential_expires_at: number | null;
        credential_observed_at?: number | null;
        refresh_token_observed_at: number | null;
        refresh_token_expires_at: number | null;
        status: string;
        rescan_recommended: boolean;
    } | null;
    wechat_error: string | null;
};
export const statusText: Record<string, [string, string]> = {
    random_window_unavailable: [
        "Selected range is outside today’s school hours",
        "所选时段不在今日学校签到时间内",
    ],
    success: ["Checked in", "已签到"],
    already_done: ["Recorded / exempt", "已记录 / 免签"],
    need_login: ["School sign-in required", "学校登录已失效"],
    wechat_expired: ["WeChat sign-in required", "需要重新登录微信"],
    scheduled: ["Scheduled", "已安排"],
    running: ["Checking…", "正在签到…"],
    retry: ["Retry scheduled", "等待重试"],
    ready: ["Ready", "就绪"],
    missed: ["Window missed", "已错过签到时间"],
    unconfirmed: ["Awaiting confirmation", "结果待确认"],
    window_not_open: ["Outside check-in hours", "未到签到时间"],
    window_missed: ["Check-in window closed", "签到时间已结束"],
    checkin_rejected: ["Submission rejected", "签到被拒绝"],
    checkin_authorization_required: [
        "Check-in authorization required",
        "需要签到授权",
    ],
    wechat_unavailable: ["WeChat unavailable", "微信服务暂不可用"],
    ticket_unavailable: ["Could not get check-in ticket", "获取签到凭证失败"],
    ticket_expired: ["Check-in ticket expired", "签到凭证已过期"],
    transport_error: ["School unavailable", "学校服务暂不可用"],
    runtime_error: ["Check failed", "签到检查失败"],
    unknown_record: ["Could not read today’s record", "无法读取今日记录"],
};
