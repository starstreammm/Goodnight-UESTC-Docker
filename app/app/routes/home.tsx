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
    ListSubheader,
    Menu,
    MenuItem,
    Paper,
    Stack,
    Typography,
} from "@mui/material";
import {
    Add,
    InfoOutlined,
    SettingsOutlined,
    PlayArrow,
    MoreHoriz,
} from "@mui/icons-material";
import { api } from "../api";
import { version } from "../../package.json";
import { useLanguage, errorText } from "../i18n";
import LoginDialog, { type LoginTarget } from "../components/LoginDialog";
import LocationDialog from "../components/LocationDialog";
import SettingsDialog from "../components/SettingsDialog";
import { type Account, type State, statusText } from "../accounts";
import AccountInfoDialog from "../components/AccountInfoDialog";
import DeleteAccountDialog from "../components/DeleteAccountDialog";
import ConsoleSettings from "../components/ConsoleSettings";
import UserDialog, {
    userActions,
    type UserAction,
} from "../components/UserDialog";
import { useAuth, type User } from "../auth";
import ConsoleHeader from "../components/ConsoleHeader";

export default function AdminHome() {
    const { user, setUser, logout } = useAuth();
    const [consoleSettings, setConsoleSettings] = useState(false);
    const [userOperation, setUserOperation] = useState<{
        target: User;
        mode: UserAction;
        personal?: boolean;
    } | null>(null);

    const { t, language } = useLanguage();
    const [state, setState] = useState<State | null>(null),
        [error, setError] = useState(""),
        [busy, setBusy] = useState(false);
    const [login, setLogin] = useState(false),
        [identity, setIdentity] = useState({
            username: "",
            alias: "",
            save_password: false,
        });
    const [newBrowser, setNewBrowser] = useState(false);
    const [aliasEditable, setAliasEditable] = useState(true);
    const [loginTarget, setLoginTarget] = useState<LoginTarget>("both");
    const [settings, setSettings] = useState<Account | null>(null),
        [location, setLocation] = useState<Account | null>(null);
    const [infoAccount, setInfoAccount] = useState<Account | null>(null);
    const [more, setMore] = useState<{
            account: Account;
            anchor: HTMLElement;
        } | null>(null),
        [remove, setRemove] = useState<Account | null>(null);
    async function refresh() {
        try {
            const next = await (await api("/state")).json();
            setState(next);
            setUser(next.user);
        } catch (e) {
            setError(errorText(e, language));
        }
    }
    useEffect(() => {
        void refresh();
        const timer = setInterval(() => void refresh(), 5000);
        return () => clearInterval(timer);
    }, [language]);
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
    function signIn(
        account?: Account,
        newFingerprint = false,
        target: LoginTarget = account ? "school" : "both",
    ) {
        setIdentity(
            account
                ? {
                      username: account.username,
                      alias: account.alias,
                      save_password: account.save_password,
                  }
                : { username: "", alias: "", save_password: false },
        );
        setAliasEditable(account?.owner_role !== "user");
        setNewBrowser(newFingerprint);
        setLoginTarget(target);
        setLogin(true);
        setMore(null);
    }
    const label = (value: string) =>
        statusText[value]
            ? t(...statusText[value])
            : t("Needs attention", "需要处理");
    const complete =
        state?.jobs.filter((j) =>
            ["success", "already_done"].includes(j.status),
        ).length || 0;
    return (
        <Container
            maxWidth={false}
            className="dashboard"
            sx={{
                p: { xs: 2, md: 3 },
                display: "flex",
                flexDirection: "column",
            }}
        >
            <ConsoleHeader
                complete={complete}
                total={state?.accounts.length}
                busy={busy}
                onLogout={() => void action(logout)}
            >
                <Button
                    startIcon={<SettingsOutlined />}
                    onClick={() => setConsoleSettings(true)}
                >
                    {t("Settings", "设置")}
                </Button>
            </ConsoleHeader>
            {!!user?.must_change_password && (
                <Alert
                    severity="warning"
                    sx={{ mb: 1 }}
                    action={
                        <Button
                            onClick={() =>
                                setUserOperation({
                                    target: user,
                                    mode: "password",
                                    personal: true,
                                })
                            }
                        >
                            {t("Change password", "修改密码")}
                        </Button>
                    }
                >
                    {t(
                        "Change your initial or reset password to protect this console.",
                        "请修改初始或重置后的密码，保护管理系统安全。",
                    )}
                </Alert>
            )}
            {error && (
                <Alert
                    severity="error"
                    onClose={() => setError("")}
                    sx={{ mb: 2 }}
                >
                    {error}
                </Alert>
            )}
            {!state ? (
                <Box sx={{ p: 5 }}>
                    <CircularProgress />
                </Box>
            ) : (
                <>
                    <Stack
                        direction="row"
                        justifyContent="space-between"
                        alignItems="center"
                        my={3}
                    >
                        <Box>
                            <Typography variant="h5">
                                {t("Your accounts", "我的账号")}
                            </Typography>
                            <Typography color="text.secondary" variant="body2">
                                {t(
                                    "School sessions and WeChat, in one place.",
                                    "统一管理学校会话与微信登录。",
                                )}
                            </Typography>
                        </Box>
                        <Button
                            variant="contained"
                            startIcon={<Add />}
                            onClick={() => signIn()}
                        >
                            {t("Add account", "添加账号")}
                        </Button>
                    </Stack>
                    <Paper
                        variant="outlined"
                        sx={{ overflow: "auto", flex: 1, minHeight: 160 }}
                    >
                        {!state.accounts.length && (
                            <Box textAlign="center" p={5}>
                                <Typography variant="h6">
                                    {t(
                                        "Make room for a good night.",
                                        "为晚安留一点时间。",
                                    )}
                                </Typography>
                                <Typography color="text.secondary" mt={1}>
                                    {t(
                                        "Connect your first account to get started.",
                                        "添加第一个账号，开始自动签到。",
                                    )}
                                </Typography>
                            </Box>
                        )}
                        {state.accounts.map((account, i) => {
                            const job = state.jobs.find(
                                (j) => j.account_id === account.id,
                            );
                            const working = state.busy_accounts.includes(
                                account.id,
                            );
                            const complete =
                                !!job &&
                                (!!job.checked_at ||
                                    !!job.checked ||
                                    ["success", "already_done"].includes(
                                        job.status,
                                    ));
                            const shownTime = complete
                                ? job?.checked_at
                                : job?.scheduled_at;
                            const status =
                                account.status === "need_login"
                                    ? "need_login"
                                    : job?.status || "ready";
                            return (
                                <Box key={account.id}>
                                    {i > 0 && <Divider />}
                                    <Box className="account">
                                        <Avatar
                                            sx={{
                                                bgcolor: "#2d4055",
                                                color: "#d4e3c6",
                                            }}
                                        >
                                            {(
                                                account.real_name ||
                                                account.username
                                            ).slice(0, 1)}
                                        </Avatar>
                                        <Box sx={{ flex: 1, minWidth: 140 }}>
                                            <Typography fontWeight={650}>
                                                {account.real_name ||
                                                    account.username}
                                            </Typography>
                                            <Typography
                                                variant="body2"
                                                color="text.secondary"
                                            >
                                                {account.username}
                                            </Typography>
                                            <Typography
                                                variant="caption"
                                                color="text.secondary"
                                            >
                                                {account.location_name ||
                                                    t(
                                                        "Loading school location…",
                                                        "正在获取学校签到位置…",
                                                    )}
                                            </Typography>
                                        </Box>
                                        <Box
                                            sx={{
                                                flex: 0.8,
                                                minWidth: 130,
                                                overflowWrap: "anywhere",
                                            }}
                                        >
                                            <Typography
                                                variant="caption"
                                                color="text.secondary"
                                            >
                                                {t(
                                                    "Associated User",
                                                    "所属用户",
                                                )}
                                            </Typography>
                                            <Typography variant="body2">
                                                {account.alias}
                                            </Typography>
                                            <Typography
                                                variant="caption"
                                                color="text.secondary"
                                            >
                                                {account.owner_username} ·{" "}
                                                {account.owner_role}
                                            </Typography>
                                        </Box>
                                        <Box
                                            className="account-log"
                                            sx={{ flex: 1.2, minWidth: 150 }}
                                        >
                                            <Typography
                                                variant="caption"
                                                color="text.secondary"
                                            >
                                                {t(
                                                    "Latest activity",
                                                    "最近记录",
                                                )}
                                            </Typography>
                                            <Typography
                                                variant="body2"
                                                sx={{
                                                    overflowWrap: "anywhere",
                                                }}
                                            >
                                                {job?.message
                                                    ? job.message in statusText
                                                        ? label(job.message)
                                                        : job.message
                                                    : t(
                                                          "No activity yet",
                                                          "暂无记录",
                                                      )}
                                            </Typography>
                                        </Box>
                                        <Box sx={{ minWidth: 140 }}>
                                            <Chip
                                                size="small"
                                                label={label(status)}
                                                color={
                                                    [
                                                        "success",
                                                        "already_done",
                                                    ].includes(status)
                                                        ? "success"
                                                        : status ===
                                                            "need_login"
                                                          ? "warning"
                                                          : "default"
                                                }
                                                variant="outlined"
                                            />
                                            {job && (
                                                <Typography
                                                    variant="caption"
                                                    display="block"
                                                    mt={1}
                                                >
                                                    {complete
                                                        ? t(
                                                              "Check-in time",
                                                              "签到时间",
                                                          )
                                                        : t(
                                                              "Scheduled",
                                                              "计划时间",
                                                          )}{" "}
                                                    ·{" "}
                                                    {shownTime
                                                        ? new Date(
                                                              shownTime,
                                                          ).toLocaleTimeString(
                                                              language === "zh"
                                                                  ? "zh-CN"
                                                                  : "en-GB",
                                                              {
                                                                  timeZone:
                                                                      "Asia/Shanghai",
                                                                  hour: "2-digit",
                                                                  minute: "2-digit",
                                                                  second: "2-digit",
                                                              },
                                                          )
                                                        : t(
                                                              "Not provided by school",
                                                              "学校未提供时间",
                                                          )}
                                                </Typography>
                                            )}
                                        </Box>
                                        <Stack
                                            direction="row"
                                            flexWrap="wrap"
                                            sx={{
                                                p: 1,
                                                gap: 1,
                                                "& .MuiButton-root": {
                                                    p: 1,
                                                    minWidth: 0,
                                                    fontSize: 13,
                                                },
                                            }}
                                        >
                                            <Button
                                                startIcon={<InfoOutlined />}
                                                onClick={() =>
                                                    setInfoAccount(account)
                                                }
                                            >
                                                {t("Info", "详情")}
                                            </Button>
                                            <Button
                                                startIcon={<SettingsOutlined />}
                                                disabled={busy || working}
                                                onClick={() =>
                                                    setSettings({ ...account })
                                                }
                                            >
                                                {t("Settings", "设置")}
                                            </Button>
                                            <Button
                                                startIcon={<PlayArrow />}
                                                disabled={
                                                    busy ||
                                                    working ||
                                                    account.status ===
                                                        "need_login"
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
                                            <Button
                                                startIcon={<MoreHoriz />}
                                                disabled={busy || working}
                                                onClick={(e) =>
                                                    setMore({
                                                        account,
                                                        anchor: e.currentTarget,
                                                    })
                                                }
                                            >
                                                {t("More", "更多")}
                                            </Button>
                                        </Stack>
                                    </Box>
                                </Box>
                            );
                        })}
                    </Paper>
                    <Stack
                        component="footer"
                        direction="row"
                        alignItems="center"
                        justifyContent="space-between"
                        sx={{ mt: 2, gap: 1, flexWrap: "wrap" }}
                    >
                        <Typography variant="caption" color="text.secondary">
                            GOODNIGHT / UESTC · Asia/Shanghai · {state.date}
                        </Typography>
                        <Chip
                            size="small"
                            variant="outlined"
                            label={`v${version}`}
                        />
                    </Stack>
                </>
            )}
            <Menu
                slotProps={{ list: { dense: true } }}
                anchorEl={more?.anchor}
                open={!!more}
                onClose={() => setMore(null)}
            >
                <ListSubheader>
                    {t("ACCOUNT ACTIONS", "账号操作")}
                </ListSubheader>
                <MenuItem onClick={() => signIn(more!.account)}>
                    {t("Sign in to school again", "重新登录学校")}
                </MenuItem>
                <MenuItem
                    onClick={() => signIn(more!.account, false, "wechat")}
                >
                    {t("Sign in to WeChat again", "重新登录微信")}
                </MenuItem>
                <MenuItem onClick={() => signIn(more!.account, true)}>
                    {t(
                        "Sign in with a new browser fingerprint",
                        "使用新浏览器指纹重新登录",
                    )}
                </MenuItem>
                <MenuItem
                    onClick={() => {
                        setRemove(more!.account);
                        setMore(null);
                    }}
                    sx={{ color: "error.main" }}
                >
                    {t("Delete account", "删除账号")}
                </MenuItem>
                <Divider />
                <ListSubheader>{t("USER ACTIONS", "用户操作")}</ListSubheader>
                {userActions.map((item) => (
                    <MenuItem
                        key={item.mode}
                        disabled={
                            (!!more?.account.owner_builtin &&
                                item.mode === "delete") ||
                            (more?.account.owner_id === user?.id &&
                                item.mode === "password")
                        }
                        onClick={() => {
                            const account = more!.account;
                            setUserOperation({
                                mode: item.mode,
                                target: {
                                    id: account.owner_id,
                                    username: account.owner_username,
                                    display_name: account.owner_display_name,
                                    role: account.owner_role,
                                    builtin: account.owner_builtin,
                                    must_change_password: 0,
                                },
                            });
                            setMore(null);
                        }}
                        sx={
                            item.mode === "delete"
                                ? { color: "error.main" }
                                : undefined
                        }
                    >
                        {t(...item.label)}
                    </MenuItem>
                ))}
            </Menu>
            <LoginDialog
                open={login}
                initial={identity}
                relogin={!!identity.username}
                newBrowser={newBrowser}
                aliasEditable={aliasEditable}
                target={loginTarget}
                onClose={() => setLogin(false)}
                onSuccess={refresh}
            />
            {location && (
                <LocationDialog
                    account={location}
                    onClose={() => setLocation(null)}
                    onSuccess={refresh}
                />
            )}
            {infoAccount && (
                <AccountInfoDialog
                    account={infoAccount}
                    onClose={() => setInfoAccount(null)}
                />
            )}
            {settings && (
                <SettingsDialog
                    account={settings}
                    onClose={() => setSettings(null)}
                    onSuccess={refresh}
                    onLocation={() => {
                        setLocation(settings);
                        setSettings(null);
                    }}
                />
            )}
            {remove && (
                <DeleteAccountDialog
                    account={remove}
                    onClose={() => setRemove(null)}
                    onSuccess={refresh}
                />
            )}
            {consoleSettings && (
                <ConsoleSettings
                    onClose={() => setConsoleSettings(false)}
                    onSuccess={refresh}
                />
            )}
            {userOperation && (
                <UserDialog
                    {...userOperation}
                    onClose={() => setUserOperation(null)}
                    onSuccess={refresh}
                />
            )}
        </Container>
    );
}
