import {
    createContext,
    useContext,
    useEffect,
    useState,
    type ReactNode,
} from "react";
import { ApiError } from "./api";
type Language = "en" | "zh";
const Context = createContext({
    language: "en" as Language,
    toggle: () => {},
    t: (en: string, zh: string) => en,
});
export function LanguageProvider({ children }: { children: ReactNode }) {
    const [language, setLanguage] = useState<Language>("en");
    useEffect(() => {
        const saved = localStorage.getItem("goodnight-language");
        setLanguage(
            saved === "zh" || saved === "en"
                ? saved
                : navigator.language.toLowerCase().startsWith("zh")
                  ? "zh"
                  : "en",
        );
    }, []);
    useEffect(() => {
        document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    }, [language]);
    function toggle() {
        const next = language === "en" ? "zh" : "en";
        setLanguage(next);
        localStorage.setItem("goodnight-language", next);
    }
    return (
        <Context.Provider
            value={{
                language,
                toggle,
                t: (en, zh) => (language === "zh" ? zh : en),
            }}
        >
            {children}
        </Context.Provider>
    );
}
export const useLanguage = () => useContext(Context);
export function errorText(error: unknown, language: string) {
    if (language === "en")
        return error instanceof Error
            ? error.message
            : "Request failed. Please try again.";
    const code = (error as { code?: string }).code;
    if (code === "login_unavailable" && error instanceof ApiError) {
        const { stage, http_status, reason, timeout_seconds } = error.details;
        const stages: Record<string, string> = {
            login_form: "加载学校登录页面",
            fingerprint_register: "注册浏览器指纹",
            captcha_check: "检查验证码",
            password_submit: "提交学校密码",
            post_redirect: "跟随登录跳转",
            sms_send: "发送短信验证码",
            sms_verify: "验证短信验证码",
            service_exchange: "获取学校会话",
            session_validate: "检查学校登录状态",
            profile_validate: "读取学校用户信息",
        };
        const action = stages[stage || ""] || "学校认证请求";
        if (Number.isInteger(http_status))
            return `${action}失败：学校服务器返回 HTTP ${http_status}${reason === "ids_unavailable" ? "（IDS is Unavailable）" : ""}。`;
        if (reason === "timeout")
            return `${action}超时${timeout_seconds ? `（${timeout_seconds} 秒）` : ""}，请稍后重试。`;
        if (reason === "network")
            return `${action}失败：无法连接学校服务器，请检查网络。`;
        if (reason === "invalid_response")
            return `${action}失败：学校返回了无法识别的响应。`;
        return `${action}失败：${error.message}`;
    }
    if (code === "schedule_unavailable")
        return "暂未获取今日学校签到时段，请等待更新后重试。";
    if (code === "invalid_checkin_range")
        return "请选择学校允许的签到时段；如学校安排已更新，请重新打开设置。";
    if (code === "review_unavailable")
        return "无法获取学校签到安排或位置，请点击重试。";
    if (code === "wechat_pending")
        return "微信凭据尚未准备好，请稍后再次确认。";
    if (code === "selected_location_unavailable")
        return "该签到位置已不可用，请重新选择。";
    return (
        (
            {
                invalid_code: "短信验证码有误，请重试。",
                expired: "登录已过期，请重新开始。",
                password_missing:
                    "未收到学校密码，请填写密码或使用已保存的密码。",
                password_required: "学校登录会话已失效，请重新登录。",
                school_session_failed:
                    "密码已提交，但后续学校会话认证未完成。这不是密码未填写，请重试并检查登录日志。",
                login_rejected: "学校在密码提交后返回了登录表单，登录未完成。",
                login_unavailable: "学校认证服务暂时不可用，请稍后重试。",
                sms_required: "需要短信验证，请重新登录。",
                wechat_expired: "微信登录已失效，请重新扫码。",
                wechat_unavailable: "暂时无法连接微信服务，请稍后重试。",
                need_login: "学校会话已过期，请重新登录。",
            } as Record<string, string>
        )[code || ""] || "操作未完成，请检查输入或稍后重试。"
    );
}
