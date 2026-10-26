import { useEffect, useState } from "react";
import {
    Alert,
    Box,
    Button,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControlLabel,
    LinearProgress,
    MenuItem,
    Stack,
    Switch,
    TextField,
    Typography,
} from "@mui/material";
import { api } from "../api";
import { useLanguage, errorText } from "../i18n";
import Captcha, { type Challenge, type Point } from "./Captcha";
import SchoolDetails, { type SchoolSchedule } from "./SchoolDetails";
export type LoginTarget = "both" | "school" | "wechat";
type Identity = { username: string; alias: string; save_password?: boolean };
type Review = {
    username: string;
    alias: string;
    detail: Record<string, unknown>;
    schedule: SchoolSchedule;
    save_password: boolean;
    location_key: string | null;
    location_changed: boolean;
    locations: {
        key: string;
        name: string;
        latitude: number;
        longitude: number;
        radiusMeter: number;
    }[];
};
type Pending = {
    login_id: string;
    state: "sms" | "captcha" | "wechat" | "wechat_confirm" | "review";
    expires_in: number;
    challenge?: Challenge;
    image?: string;
    expires: number;
    review?: Review;
};
export default function LoginDialog({
    open,
    initial,
    relogin = false,
    newBrowser = false,
    target = "both",
    onClose,
    onSuccess,
}: {
    open: boolean;
    initial: Identity;
    relogin?: boolean;
    newBrowser?: boolean;
    target?: LoginTarget;
    onClose: () => void;
    onSuccess: () => Promise<void>;
}) {
    const { t, language } = useLanguage();
    const [identity, setIdentity] = useState(initial),
        [password, setPassword] = useState(""),
        [code, setCode] = useState("");
    const [savePassword, setSavePassword] = useState(false),
        [pending, setPending] = useState<Pending | null>(null);
    const [busy, setBusy] = useState(false),
        [error, setError] = useState(""),
        [clock, setClock] = useState(Date.now());
    const [locationKey, setLocationKey] = useState(""),
        [pollRetry, setPollRetry] = useState(0);
    useEffect(() => {
        if (open) {
            setIdentity(initial);
            setPassword("");
            setCode("");
            setSavePassword(!!initial.save_password);
            setPending(null);
            setError("");
        }
    }, [open, initial]);
    const expired = !!pending && clock >= pending.expires;
    useEffect(() => {
        if (!pending) return;
        const timer = setInterval(() => setClock(Date.now()), 1000);
        return () => clearInterval(timer);
    }, [pending]);
    async function accept(result: Pending & { ok?: boolean }) {
        if (result.ok) {
            setPending(null);
            setPassword("");
            setCode("");
            onClose();
            await onSuccess();
            return;
        }
        if (result.review)
            setLocationKey(
                result.review.location_key ||
                    result.review.locations[0]?.key ||
                    "",
            );
        setError("");
        setPending({
            ...result,
            expires: Date.now() + result.expires_in * 1000,
        });
        setClock(Date.now());
    }
    useEffect(() => {
        if (pending?.state !== "wechat" || expired) return;
        let active = true,
            timer: ReturnType<typeof setTimeout>;
        async function poll() {
            try {
                const result = await (
                    await api(`/logins/${pending!.login_id}/wechat`)
                ).json();
                if (!active) return;
                if (
                    result.ok ||
                    result.state === "review" ||
                    result.state === "wechat_confirm"
                ) {
                    await accept(result);
                    return;
                }
                timer = setTimeout(poll, 2000);
            } catch (e) {
                if (active) setError(errorText(e, language));
            }
        }
        timer = setTimeout(poll, 1000);
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [pending?.login_id, pending?.state, expired, language, pollRetry]);
    async function run(fn: () => Promise<void>) {
        setBusy(true);
        setError("");
        try {
            await fn();
        } catch (e) {
            setError(errorText(e, language));
        } finally {
            setBusy(false);
        }
    }
    async function cancel() {
        if (pending) await api(`/logins/${pending.login_id}`, "DELETE");
        setPending(null);
        setCode("");
        setPassword("");
    }
    async function send(path: string, data: unknown) {
        await accept(await (await api(path, "POST", data)).json());
    }
    async function submit(form: FormData) {
        if (expired) {
            await cancel();
            return;
        }
        if (pending?.state === "sms") {
            const value = code;
            setCode("");
            await send(`/logins/${pending.login_id}/code`, { code: value });
            return;
        }
        if (pending?.state === "review") {
            await send(`/logins/${pending.login_id}/confirm`, {
                key: locationKey,
            });
            return;
        }
        if (pending?.state === "wechat_confirm") {
            await send(`/logins/${pending.login_id}/confirm`, {});
            return;
        }
        if (pending) return;
        const value = String(form.get("school_password") ?? password);
        setPassword("");
        await send("/accounts", {
            ...identity,
            username: String(form.get("username") ?? identity.username),
            save_password: savePassword,
            password: value || undefined,
            new_browser_fingerprint: newBrowser,
            login_target: target,
        });
    }
    function drag(ticket: string, points: Point[]) {
        void run(() =>
            send(`/logins/${pending!.login_id}/captcha`, { ticket, points }),
        );
    }
    const review = pending?.review;
    const selected =
        review?.locations.find((location) => location.key === locationKey) ||
        (!locationKey ? review?.locations[0] : undefined);
    return (
        <Dialog
            open={open}
            onClose={() =>
                !busy &&
                void run(async () => {
                    await cancel();
                    onClose();
                })
            }
            fullWidth
            maxWidth="sm"
        >
            <DialogTitle>
                {pending?.state === "review"
                    ? t("Confirm account", "确认账号")
                    : newBrowser
                      ? t(
                            "Sign in with a new browser fingerprint",
                            "使用新浏览器指纹重新登录",
                        )
                      : target === "school"
                        ? t("Sign in to school again", "重新登录学校")
                        : target === "wechat"
                          ? t("Sign in to WeChat again", "重新登录微信")
                          : relogin
                            ? t("Sign in again", "重新登录")
                            : t("Add an account", "添加账号")}
            </DialogTitle>
            <Box
                component="form"
                onSubmit={(e) => {
                    e.preventDefault();
                    const form = new FormData(e.currentTarget);
                    void run(() => submit(form));
                }}
            >
                <DialogContent>
                    <Stack spacing={2}>
                        <Typography color="text.secondary">
                            {target === "school"
                                ? t(
                                      "School account → SMS if required → Review",
                                      "学校账号 → 按需短信验证 → 确认信息",
                                  )
                                : target === "wechat"
                                  ? t(
                                        "Scan WeChat → Confirm binding",
                                        "微信扫码 → 确认绑定",
                                    )
                                  : t(
                                        "School account → SMS if required → WeChat → Review",
                                        "学校账号 → 按需短信验证 → 微信扫码 → 确认信息",
                                    )}
                        </Typography>
                        {error && <Alert severity="error">{error}</Alert>}
                        {!pending && target === "wechat" && (
                            <Typography>
                                {identity.alias || identity.username} ·{" "}
                                {t(
                                    "Continue to get a new WeChat QR code.",
                                    "点击继续获取新的微信二维码。",
                                )}
                            </Typography>
                        )}
                        {!pending && target !== "wechat" && (
                            <>
                                {newBrowser && (
                                    <Alert severity="info">
                                        {t(
                                            "Start a fresh school login with a new browser fingerprint. Confirm to save the new school credentials.",
                                            "使用新浏览器指纹从头登录学校账号，确认后保存新的学校登录凭据。",
                                        )}
                                    </Alert>
                                )}
                                <TextField
                                    label={t(
                                        "Username / student ID",
                                        "用户名 / 学号",
                                    )}
                                    name="username"
                                    autoComplete="username"
                                    required
                                    disabled={busy || relogin}
                                    value={identity.username}
                                    onChange={(e) =>
                                        setIdentity({
                                            ...identity,
                                            username: e.target.value,
                                        })
                                    }
                                />
                                <TextField
                                    label={t(
                                        "Alias (optional)",
                                        "别名（可选）",
                                    )}
                                    helperText={t(
                                        "Defaults to your real name from the school.",
                                        "留空则使用学校返回的真实姓名。",
                                    )}
                                    disabled={busy}
                                    value={identity.alias}
                                    onChange={(e) =>
                                        setIdentity({
                                            ...identity,
                                            alias: e.target.value,
                                        })
                                    }
                                />
                                <TextField
                                    label={t("School password", "学校密码")}
                                    helperText={
                                        initial.save_password
                                            ? t(
                                                  "Leave blank to use the saved password.",
                                                  "留空可使用已保存的密码。",
                                              )
                                            : undefined
                                    }
                                    name="school_password"
                                    type="password"
                                    autoComplete="current-password"
                                    required={!initial.save_password}
                                    disabled={busy}
                                    value={password}
                                    onChange={(e) =>
                                        setPassword(e.target.value)
                                    }
                                />
                                <FormControlLabel
                                    control={
                                        <Switch
                                            checked={savePassword}
                                            disabled={busy}
                                            onChange={(e) =>
                                                setSavePassword(
                                                    e.target.checked,
                                                )
                                            }
                                        />
                                    }
                                    label={t(
                                        "Save password locally for renewal",
                                        "本地保存密码，用于自动续期",
                                    )}
                                />
                                <Typography
                                    variant="body2"
                                    color="text.secondary"
                                >
                                    {savePassword
                                        ? t(
                                              "The password is encrypted locally. The school may still require SMS verification.",
                                              "密码将加密保存在本地。续期时学校仍可能要求短信验证。",
                                          )
                                        : t(
                                              "Your session can be used for up to seven days. After that, enter your password again.",
                                              "会话最多使用七天，到期后需要重新输入密码。",
                                          )}
                                </Typography>
                            </>
                        )}
                        {pending?.state === "sms" && !expired && (
                            <>
                                <Alert severity="info">
                                    {t(
                                        "A code was sent to your school-linked phone.",
                                        "验证码已发送至学校账号绑定的手机。",
                                    )}
                                </Alert>
                                <TextField
                                    label={t("SMS code", "短信验证码")}
                                    autoComplete="one-time-code"
                                    autoFocus
                                    required
                                    value={code}
                                    disabled={busy}
                                    onChange={(e) => setCode(e.target.value)}
                                    slotProps={{
                                        htmlInput: {
                                            inputMode: "numeric",
                                            pattern: "[0-9]{4,10}",
                                            maxLength: 10,
                                        },
                                    }}
                                />
                            </>
                        )}
                        {pending?.state === "captcha" &&
                            pending.challenge &&
                            !expired && (
                                <Captcha
                                    challenge={pending.challenge}
                                    disabled={busy}
                                    onDrag={drag}
                                    onRefresh={() =>
                                        void run(() =>
                                            send(
                                                `/logins/${pending.login_id}/captcha/refresh`,
                                                {},
                                            ),
                                        )
                                    }
                                />
                            )}
                        {pending?.state === "wechat" && !expired && (
                            <>
                                <Typography>
                                    {t(
                                        "Scan with WeChat and confirm on your phone.",
                                        "请使用微信扫码，并在手机上确认登录。",
                                    )}
                                </Typography>
                                <Box
                                    component="img"
                                    src={pending.image}
                                    alt={t(
                                        "WeChat sign-in QR code",
                                        "微信登录二维码",
                                    )}
                                    sx={{
                                        width: 240,
                                        maxWidth: "100%",
                                        alignSelf: "center",
                                        borderRadius: 2,
                                    }}
                                />
                                <Typography
                                    variant="caption"
                                    color="text.secondary"
                                >
                                    {t(
                                        "Waiting for confirmation…",
                                        "等待确认…",
                                    )}
                                </Typography>
                            </>
                        )}
                        {pending?.state === "wechat_confirm" && !expired && (
                            <Alert severity="success">
                                {t(
                                    "WeChat authorized. Confirm to save this WeChat binding.",
                                    "微信已授权，请确认保存新的微信绑定。",
                                )}
                            </Alert>
                        )}
                        {pending?.state === "review" && review && (
                            <>
                                <Alert severity="info">
                                    {t(
                                        "Review the school information and location. Confirm to save the account and enable scheduling.",
                                        "请核对学校信息和签到位置。确认后才会保存账号并启用自动签到。",
                                    )}
                                </Alert>
                                <Typography fontWeight={650}>
                                    {review.alias} · {review.username}
                                </Typography>
                                <SchoolDetails
                                    detail={review.detail}
                                    schedule={review.schedule}
                                />
                                {review.location_changed && (
                                    <Alert severity="warning">
                                        {t(
                                            "The previous location is no longer available. Choose a location below.",
                                            "原签到位置已不可用，请重新选择。",
                                        )}
                                    </Alert>
                                )}
                                <TextField
                                    select
                                    label={t("Check-in location", "签到位置")}
                                    value={locationKey}
                                    disabled={busy || expired}
                                    onChange={(event) =>
                                        setLocationKey(event.target.value)
                                    }
                                >
                                    {review.locations.map((location) => (
                                        <MenuItem
                                            key={location.key}
                                            value={location.key}
                                        >
                                            {location.name}
                                        </MenuItem>
                                    ))}
                                </TextField>
                                {selected && (
                                    <Typography
                                        variant="body2"
                                        color="text.secondary"
                                    >
                                        {selected.name}
                                        <br />
                                        {t(
                                            "Latitude / longitude",
                                            "纬度 / 经度",
                                        )}{" "}
                                        · {selected.latitude},{" "}
                                        {selected.longitude}
                                        <br />
                                        {t("Allowed radius", "允许范围")} ·{" "}
                                        {selected.radiusMeter} m
                                    </Typography>
                                )}
                                <Typography variant="body2">
                                    {t(
                                        "Password saved locally",
                                        "在本地保存密码",
                                    )}{" "}
                                    ·{" "}
                                    {review.save_password
                                        ? t("Yes", "是")
                                        : t("No", "否")}
                                </Typography>
                                <Typography
                                    variant="caption"
                                    color="text.secondary"
                                >
                                    {t(
                                        "The school session lease lasts up to seven days after confirmation.",
                                        "学校会话从确认后起最多有效七天。",
                                    )}
                                </Typography>
                            </>
                        )}
                        {pending && (
                            <Box>
                                <Typography variant="caption">
                                    {t("Time remaining", "剩余时间")} ·{" "}
                                    {Math.max(
                                        0,
                                        Math.ceil(
                                            (pending.expires - clock) / 1000,
                                        ),
                                    )}
                                    s
                                </Typography>
                                <LinearProgress
                                    variant="determinate"
                                    value={Math.max(
                                        0,
                                        Math.min(
                                            100,
                                            (pending.expires - clock) / 3000,
                                        ),
                                    )}
                                    aria-label={t(
                                        "Login time remaining",
                                        "登录剩余时间",
                                    )}
                                    sx={{ mt: 0.5, height: 5, borderRadius: 3 }}
                                />
                            </Box>
                        )}
                        {expired && (
                            <Alert severity="warning">
                                {t(
                                    "Login expired. Start again.",
                                    "登录已过期，请重新开始。",
                                )}
                            </Alert>
                        )}
                        {busy && <CircularProgress size={22} />}
                    </Stack>
                </DialogContent>
                <DialogActions sx={{ p: 3 }}>
                    <Button
                        disabled={busy}
                        onClick={() =>
                            void run(async () => {
                                await cancel();
                                onClose();
                            })
                        }
                    >
                        {t("Cancel", "取消")}
                    </Button>
                    {pending && (
                        <Button
                            disabled={busy}
                            onClick={() => void run(cancel)}
                        >
                            {t("Start again", "重新开始")}
                        </Button>
                    )}
                    {pending?.state === "wechat" && error && !expired && (
                        <Button
                            onClick={() => {
                                setError("");
                                setPollRetry((value) => value + 1);
                            }}
                        >
                            {t("Retry", "重试")}
                        </Button>
                    )}
                    {pending?.state === "wechat_confirm" && !expired && (
                        <Button
                            type="submit"
                            variant="contained"
                            disabled={busy}
                        >
                            {t("Confirm WeChat", "确认微信绑定")}
                        </Button>
                    )}
                    {pending?.state === "review" && !expired && (
                        <Button
                            type="submit"
                            variant="contained"
                            disabled={busy || !selected}
                        >
                            {t("Confirm and save", "确认并保存")}
                        </Button>
                    )}
                    {(!pending || pending.state === "sms") && !expired && (
                        <Button
                            type="submit"
                            variant="contained"
                            disabled={busy}
                        >
                            {pending
                                ? t("Verify code", "验证")
                                : t("Continue", "继续")}
                        </Button>
                    )}
                </DialogActions>
            </Box>
        </Dialog>
    );
}
