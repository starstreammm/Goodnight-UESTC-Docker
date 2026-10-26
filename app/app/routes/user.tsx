import { useEffect, useState } from "react";
import {
    Alert,
    Avatar,
    Box,
    Button,
    Chip,
    CircularProgress,
    Container,
    Divider,
    Paper,
    Menu,
    MenuItem,
    Stack,
    Typography,
} from "@mui/material";
import { Add, MoreHoriz, PlayArrow, Refresh } from "@mui/icons-material";
import { api } from "../api";
import { useAuth } from "../auth";
import { useLanguage, errorText } from "../i18n";
import { type State, type Info, statusText } from "../accounts";
import LoginDialog, { type LoginTarget } from "../components/LoginDialog";
import AccountSettingsForm from "../components/AccountSettingsForm";
import SchoolDetails, { SchoolCheckinSchedule } from "../components/SchoolDetails";
import ExpiryProgress from "../components/ExpiryProgress";
import LocationSelect from "../components/LocationSelect";
import DeleteAccountDialog from "../components/DeleteAccountDialog";
import UserDialog from "../components/UserDialog";
import ConsoleHeader from "../components/ConsoleHeader";
import { version } from "../../package.json";

export default function UserHome() {
    const { user, setUser, logout } = useAuth();
    const { t, language } = useLanguage();
    const [state, setState] = useState<State | null>(null);
    const [info, setInfo] = useState<Info | null>(null);
    const [infoError, setInfoError] = useState("");
    const [infoRevision, setInfoRevision] = useState(0);
    const [busy, setBusy] = useState(false);
    const [saving, setSaving] = useState(false);
    const [locationBusy, setLocationBusy] = useState(false);
    const [actionsAnchor, setActionsAnchor] = useState<HTMLElement | null>(null);
    const [error, setError] = useState("");
    const [dialog, setDialog] = useState<
        "delete" | "profile" | "password" | "delete-user" | null
    >(null);
    const [login, setLogin] = useState<{
        target: LoginTarget;
        newBrowser: boolean;
        identity: { username: string; alias: string; save_password: boolean };
    } | null>(null);
    const account = state?.accounts[0];
    const job = state?.jobs.find((j) => j.account_id === account?.id);
    const working = !!account && !!state?.busy_accounts.includes(account.id);
    const disabled = busy || saving || locationBusy || working || !!login;
    const complete =
        !!job &&
        (!!job.checked_at ||
            !!job.checked ||
            ["success", "already_done"].includes(job.status));
    const shownTime = complete ? job?.checked_at : job?.scheduled_at;
    const label = (value: string) =>
        statusText[value] ? t(...statusText[value]) : value;
    const status = account?.status === "need_login"
        ? "need_login"
        : job?.status || "ready";
    function signIn(target: LoginTarget, newBrowser = false) {
        setLogin({
            target,
            newBrowser,
            identity: account
                ? {
                    username: account.username,
                    alias: account.alias,
                    save_password: account.save_password,
                }
                : {
                    username: "",
                    alias: user!.display_name.trim() || user!.username,
                    save_password: false,
                },
        });
    }
    async function refresh() {
        const next = await (await api("/state")).json();
        setState(next);
        setUser(next.user);
    }
    async function refreshAccount() {
        await refresh();
        setInfoRevision((value) => value + 1);
    }
    async function action(fn: () => Promise<void>) {
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
    useEffect(() => {
        let active = true;
        const load = async () => {
            try {
                const next = await (await api("/state")).json();
                if (active) {
                    setState(next);
                    setUser(next.user);
                }
            } catch (e) {
                if (active) setError(errorText(e, language));
            }
        };
        void load();
        const timer = setInterval(() => void load(), 5000);
        return () => {
            active = false;
            clearInterval(timer);
        };
    }, [language]);
    useEffect(() => {
        let active = true;
        setInfo(null);
        setInfoError("");
        if (account)
            void api(`/accounts/${account.id}/info`)
                .then((r) => r.json())
                .then((value) => {
                    if (active) setInfo(value);
                })
                .catch((e) => {
                    if (active) setInfoError(errorText(e, language));
                });
        return () => {
            active = false;
        };
    }, [
        account?.id,
        account?.uestc_expires_at,
        account?.wechat_ref,
        account?.school_window,
        account?.location_name,
        state?.date,
        infoRevision,
        language,
    ]);
    return (
        <Container
            maxWidth={false}
            className="user-console"
            sx={{ p: 2 }}
        >
            <ConsoleHeader
                busy={busy || saving || locationBusy}
                onLogout={() => void action(logout)}
            >
                <Button
                    size="small"
                    disabled={busy || saving || locationBusy}
                    onClick={() => setDialog("profile")}
                >
                    {t("My profile", "个人资料")}
                </Button>
                <Button
                    size="small"
                    disabled={busy || saving || locationBusy}
                    onClick={() => setDialog("password")}
                >
                    {t("Change password", "修改密码")}
                </Button>
            </ConsoleHeader>
            {!!user?.must_change_password && (
                <Alert severity="warning" sx={{ mb: 1 }}>
                    {t(
                        "Please change your initial or reset password.",
                        "请修改初始或重置后的密码。",
                    )}
                </Alert>
            )}
            {error && (
                <Alert
                    severity="error"
                    onClose={() => setError("")}
                    sx={{ mb: 1 }}
                >
                    {error}
                </Alert>
            )}
            <Box component="main" className="user-content">
                <Paper
                    variant="outlined"
                    className="user-account-panel"
                >
                    <Box
                        className="account user-account-row"
                        sx={{ borderBottom: 1, borderColor: "divider" }}
                    >
                        <Avatar sx={{ bgcolor: "#2d4055", color: "#d4e3c6" }}>
                            {(account?.real_name || account?.username || user!.username).slice(0, 1)}
                        </Avatar>
                        <Box sx={{ flex: 1, minWidth: 140, overflowWrap: "anywhere" }}>
                            <Typography fontWeight={650}>
                                {account?.real_name || account?.username || user?.username}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {account?.username || t("Not connected", "未关联")}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                                {account?.location_name || t("No location selected", "尚未选择位置")}
                            </Typography>
                        </Box>
                        {account && (
                            <>
                                <Box sx={{ flex: 0.8, minWidth: 130, overflowWrap: "anywhere" }}>
                                    <Typography variant="caption" color="text.secondary">
                                        {t("Associated User", "所属用户")}
                                    </Typography>
                                    <Typography variant="body2">{account.alias}</Typography>
                                    <Typography variant="caption" color="text.secondary">
                                        {account.owner_username} · {account.owner_role}
                                    </Typography>
                                </Box>
                                <Box className="account-log" sx={{ flex: 1.2, minWidth: 150 }}>
                                    <Typography variant="caption" color="text.secondary">
                                        {t("Latest activity", "最近记录")}
                                    </Typography>
                                    <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>
                                        {job?.message ? label(job.message) : t("No activity yet", "暂无记录")}
                                    </Typography>
                                </Box>
                                <Box sx={{ minWidth: 140 }}>
                                    <Chip
                                        size="small"
                                        label={label(status)}
                                        color={["success", "already_done"].includes(status)
                                            ? "success"
                                            : status === "need_login" ? "warning" : "default"}
                                        variant="outlined"
                                    />
                                    {job && (
                                        <Typography variant="caption" display="block" mt={1}>
                                            {complete ? t("Check-in time", "签到时间") : t("Scheduled", "计划时间")} ·{" "}
                                            {shownTime
                                                ? new Date(shownTime).toLocaleTimeString(
                                                    language === "zh" ? "zh-CN" : "en-GB",
                                                    { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", second: "2-digit" },
                                                )
                                                : t("Not provided by school", "学校未提供时间")}
                                        </Typography>
                                    )}
                                </Box>
                            </>
                        )}
                        <Stack
                            component="nav"
                            aria-label={t("Account actions", "账号操作")}
                            direction="row"
                            flexWrap="wrap"
                            sx={{
                                p: 1,
                                gap: 1,
                                "& .MuiButton-root": { p: 1, minWidth: 0, fontSize: 13 },
                            }}
                        >
                            {account ? (
                                <Button
                                    size="small"
                                    startIcon={<PlayArrow />}
                                    disabled={
                                        disabled ||
                                        account.status === "need_login"
                                    }
                                    onClick={() =>
                                        void action(async () => {
                                            await api(
                                                `/accounts/${account.id}/check-in`,
                                                "POST",
                                            );
                                            await refresh();
                                        })
                                    }
                                >
                                    {t("Run now", "立即运行")}
                                </Button>
                            ) : (
                                state && (
                                    <Button
                                        size="small"
                                        variant="contained"
                                        startIcon={<Add />}
                                        disabled={disabled}
                                        onClick={() => signIn("both")}
                                    >
                                        {t("Create Account", "添加账号")}
                                    </Button>
                                )
                            )}
                            <Button
                                size="small"
                                startIcon={<Refresh />}
                                disabled={disabled}
                                onClick={() => void action(refreshAccount)}
                            >
                                {t("Refresh", "刷新")}
                            </Button>
                            {account && (
                                <Button
                                    size="small"
                                    startIcon={<MoreHoriz />}
                                    disabled={disabled}
                                    aria-controls={actionsAnchor ? "school-account-actions" : undefined}
                                    aria-haspopup="menu"
                                    aria-expanded={!!actionsAnchor}
                                    onClick={(event) => setActionsAnchor(event.currentTarget)}
                                >
                                    {t("More", "更多")}
                                </Button>
                            )}
                            {account && (
                                <Menu
                                    id="school-account-actions"
                                    anchorEl={actionsAnchor}
                                    open={!!actionsAnchor}
                                    onClose={() => setActionsAnchor(null)}
                                    onClick={() => setActionsAnchor(null)}
                                    anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
                                    transformOrigin={{ vertical: "top", horizontal: "right" }}
                                >
                                    <MenuItem
                                        disabled={disabled}
                                        onClick={() => signIn("school")}
                                    >
                                        {t(
                                            "Sign in to school again",
                                            "重新登录学校",
                                        )}
                                    </MenuItem>
                                    <MenuItem
                                        disabled={disabled}
                                        onClick={() => signIn("wechat")}
                                    >
                                        {t(
                                            "Sign in to WeChat again",
                                            "重新登录微信",
                                        )}
                                    </MenuItem>
                                    <MenuItem
                                        disabled={disabled}
                                        onClick={() => signIn("school", true)}
                                    >
                                        {t(
                                            "New browser fingerprint",
                                            "更换浏览器指纹",
                                        )}
                                    </MenuItem>
                                    {account.save_password && (
                                        <MenuItem
                                            sx={{ color: "warning.main" }}
                                            disabled={disabled}
                                            onClick={() =>
                                                void action(async () => {
                                                    await api(
                                                        `/accounts/${account.id}/password`,
                                                        "DELETE",
                                                    );
                                                    await refreshAccount();
                                                })
                                            }
                                        >
                                            {t(
                                                "Forget saved password",
                                                "删除已保存密码",
                                            )}
                                        </MenuItem>
                                    )}
                                    <MenuItem
                                        sx={{ color: "error.main" }}
                                        disabled={disabled}
                                        onClick={() => setDialog("delete")}
                                    >
                                        {t("Delete Account", "删除账号")}
                                    </MenuItem>
                                </Menu>
                            )}
                        </Stack>
                    </Box>
                    <Box className="user-account-body">
                        {!state ? (
                            <Box
                                sx={{
                                    display: "grid",
                                    placeItems: "center",
                                    flex: 1,
                                }}
                            >
                                <CircularProgress />
                            </Box>
                        ) : !account ? (
                            <Stack
                                justifyContent="center"
                                alignItems="center"
                                spacing={1}
                                sx={{ flex: 1, textAlign: "center" }}
                            >
                                <Typography fontWeight={600}>
                                    {t("No Account connected", "尚未关联账号")}
                                </Typography>
                                <Typography
                                    variant="body2"
                                    color="text.secondary"
                                >
                                    {t(
                                        "Use Create Account above to connect your school Account.",
                                        "点击上方“添加账号”，关联学校账号。",
                                    )}
                                </Typography>
                            </Stack>
                        ) : (
                            <Box className="user-account-details">
                                <Stack component="section" spacing={1.25} sx={{ minWidth: 0 }}>
                                    <Typography
                                        variant="subtitle2"
                                    >
                                        {t("Account profile", "账号资料")}
                                    </Typography>
                                    <SchoolCheckinSchedule schedule={info?.schedule} />
                                    <Divider />
                                    {infoError ? (
                                        <Alert severity="error">
                                            {infoError}
                                        </Alert>
                                    ) : !info ? (
                                        <CircularProgress size={24} />
                                    ) : (
                                        <SchoolDetails
                                            detail={info.detail}
                                            showSchedule={false}
                                        />
                                    )}
                                </Stack>
                                <Stack component="section" className="user-settings" spacing={1.25}>
                                    <Typography variant="subtitle2">
                                        {t("Account settings", "账号设置")}
                                    </Typography>
                                    <LocationSelect
                                        key={account.id}
                                        accountId={account.id}
                                        revision={infoRevision}
                                        locationName={account.location_name}
                                        disabled={busy || saving || !!login}
                                        working={working}
                                        onSuccess={refresh}
                                        onBusyChange={setLocationBusy}
                                    />
                                    <AccountSettingsForm
                                        key={`${account.id}:${account.school_window}:${account.checkin_time}`}
                                        account={account}
                                        formId="user-account-settings"
                                        autoSave
                                        disabled={disabled}
                                        onSuccess={refresh}
                                        onBusyChange={setSaving}
                                    />
                                    <Divider />
                                    <Box className="user-credentials">
                                        <ExpiryProgress
                                            title={t(
                                                "School session",
                                                "学校会话",
                                            )}
                                            expiresAt={account.uestc_expires_at}
                                            startsAt={
                                                account.uestc_expires_at
                                                    ? account.uestc_expires_at -
                                                    7 * 86400
                                                    : null
                                            }
                                        />
                                        {info && (
                                            <>
                                                <ExpiryProgress
                                                    title={t(
                                                        "WeChat credentials",
                                                        "微信凭据",
                                                    )}
                                                    expiresAt={
                                                        info.wechat
                                                            ?.credential_expires_at
                                                    }
                                                    startsAt={
                                                        info.wechat
                                                            ?.credential_observed_at
                                                    }
                                                />
                                                {info.wechat_error && (
                                                    <Alert severity="warning">
                                                        {label(
                                                            info.wechat_error,
                                                        )}
                                                    </Alert>
                                                )}
                                            </>
                                        )}
                                    </Box>
                                    <Typography
                                        variant="caption"
                                        color="text.secondary"
                                    >
                                        {t("Password saved", "已保存密码")}:{" "}
                                        {account.save_password
                                            ? t("Yes", "是")
                                            : t("No", "否")}
                                        .{" "}
                                        {t(
                                            "To save a new school password, use Sign in to school again.",
                                            "如需保存新的学校密码，请使用上方“重新登录学校”。",
                                        )}
                                    </Typography>
                                </Stack>
                            </Box>
                        )}
                    </Box>
                </Paper>
            </Box>
            <Stack
                component="footer"
                direction="row"
                alignItems="center"
                justifyContent="space-between"
                sx={{ pt: 1.5, gap: 1, flexWrap: "wrap", flexShrink: 0 }}
            >
                <Typography variant="caption" color="text.secondary">
                    GOODNIGHT / UESTC · Asia/Shanghai
                    {state ? ` · ${state.date}` : ""}
                </Typography>
                <Chip size="small" variant="outlined" label={`v${version}`} />
            </Stack>
            {login && (
                <LoginDialog
                    open
                    initial={login.identity}
                    aliasEditable={false}
                    relogin={!!login.identity.username}
                    newBrowser={login.newBrowser}
                    target={login.target}
                    onClose={() => setLogin(null)}
                    onSuccess={refreshAccount}
                />
            )}
            {account && dialog === "delete" && (
                <DeleteAccountDialog
                    account={account}
                    onClose={() => setDialog(null)}
                    onSuccess={refreshAccount}
                />
            )}
            {(dialog === "profile" || dialog === "password" || dialog === "delete-user") && (
                <UserDialog
                    key={dialog}
                    personal
                    target={{ ...user!, account_count: state?.accounts.length }}
                    mode={
                        dialog === "profile"
                            ? "edit"
                            : dialog === "delete-user"
                                ? "delete"
                                : "password"
                    }
                    onClose={() => setDialog(null)}
                    onSuccess={refreshAccount}
                    onDelete={() => setDialog("delete-user")}
                />
            )}
        </Container>
    );
}
