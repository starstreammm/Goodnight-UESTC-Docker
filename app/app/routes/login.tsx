import { useEffect, useState } from "react";
import PageRedirect from "../components/PageRedirect";
import {
    Alert,
    Box,
    Button,
    CircularProgress,
    Container,
    Paper,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { api, ApiError } from "../api";
import { useAuth, userHomePath } from "../auth";
import { useLanguage, errorText } from "../i18n";

export default function LoginPage() {
    const { user, loading, error: sessionError, setUser, refresh } = useAuth();
    const { t, language, toggle } = useLanguage();
    const [register, setRegister] = useState(false);
    const [mode, setMode] = useState("disabled");
    const [username, setUsername] = useState("");
    const [displayName, setDisplayName] = useState("");
    const [password, setPassword] = useState("");
    const [invitation, setInvitation] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [wrongPassword, setWrongPassword] = useState(false);
    useEffect(() => {
        const load = () =>
            void api("/auth/registration")
                .then((r) => r.json())
                .then((v) => setMode(v.registration_mode))
                .catch((e) => setError(errorText(e, language)));
        load();
        window.addEventListener("focus", load);
        return () => window.removeEventListener("focus", load);
    }, [language]);
    if (loading) return <CircularProgress sx={{ m: 3 }} />;
    if (user) return <PageRedirect to={userHomePath(user)} />;
    return (
        <Container
            maxWidth="xs"
            sx={{
                minHeight: "100dvh",
                py: 3,
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
            }}
        >
            <Paper variant="outlined" sx={{ p: 2 }}>
                <Stack
                    component="form"
                    spacing={2}
                    onSubmit={async (e) => {
                        e.preventDefault();
                        setBusy(true);
                        setError("");
                        setWrongPassword(false);
                        try {
                            const result = await api(
                                register ? "/auth/register" : "/auth/login",
                                "POST",
                                {
                                    username,
                                    password,
                                    ...(register
                                        ? {
                                              display_name: displayName,
                                              invitation,
                                          }
                                        : {}),
                                },
                            );
                            setUser(await result.json());
                        } catch (e) {
                            setError(errorText(e, language));
                            setWrongPassword(
                                e instanceof ApiError && e.code === "wrong_password",
                            );
                        } finally {
                            setBusy(false);
                        }
                    }}
                >
                    <Box
                        display="flex"
                        justifyContent="space-between"
                        alignItems="center"
                    >
                        <Typography variant="h6">GoodNight</Typography>
                        <Button onClick={toggle}>
                            {language === "en" ? "中文" : "English"}
                        </Button>
                    </Box>
                    <Typography>
                        {register
                            ? t("Create a User", "注册用户")
                            : t("Log in to your console", "登录管理系统")}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                        {t(
                            "Use your console credentials, separate from your school account.",
                            "请使用管理系统用户名和密码，与学校账号分开。",
                        )}
                    </Typography>
                    {(error || sessionError) && (
                        <Alert severity="error">
                            {error || sessionError}
                            {sessionError && (
                                <Button onClick={() => void refresh()}>
                                    {t("Retry", "重试")}
                                </Button>
                            )}
                        </Alert>
                    )}
                    <TextField
                        size="small"
                        required
                        label={t("Username", "用户名")}
                        value={username}
                        onChange={(e) => {
                            setUsername(e.target.value);
                            if (wrongPassword) setError("");
                            setWrongPassword(false);
                        }}
                        autoComplete="username"
                        helperText={
                            register
                                ? t(
                                      "1–64 characters: English letters, numbers, underscores (_), dots (.), and hyphens (-) only. Chinese characters and spaces are not allowed.",
                                      "1–64 个字符，仅限英文字母、数字、下划线（_）、点（.）和连字符（-），不能使用中文或空格。",
                                  )
                                : undefined
                        }
                        slotProps={{
                            htmlInput: {
                                maxLength: 64,
                                pattern: "[a-zA-Z0-9_.\\-]+",
                                autoCapitalize: "none",
                                spellCheck: false,
                            },
                        }}
                    />
                    {register && (
                        <TextField
                            size="small"
                            label={t("Display name", "显示名称")}
                            value={displayName}
                            onChange={(e) => setDisplayName(e.target.value)}
                            slotProps={{ htmlInput: { maxLength: 80 } }}
                        />
                    )}
                    <TextField
                        size="small"
                        required
                        type="password"
                        label={t("Password", "密码")}
                        value={password}
                        onChange={(e) => {
                            setPassword(e.target.value);
                            if (wrongPassword) setError("");
                            setWrongPassword(false);
                        }}
                        error={wrongPassword}
                        autoComplete={
                            register ? "new-password" : "current-password"
                        }
                        slotProps={{
                            htmlInput: {
                                minLength: register ? 8 : 1,
                                maxLength: 128,
                            },
                        }}
                        helperText={
                            wrongPassword
                                ? t("Wrong password", "密码错误")
                                : register
                                    ? t("8–128 characters", "8–128 个字符")
                                    : undefined
                        }
                    />
                    {register && mode === "invitation" && (
                        <TextField
                            size="small"
                            required
                            label={t("Invitation code", "邀请码")}
                            value={invitation}
                            onChange={(e) => setInvitation(e.target.value)}
                            autoComplete="off"
                            helperText={t(
                                "Contact the administrator to get an invitation code.",
                                "请联系管理员获取邀请码。",
                            )}
                        />
                    )}
                    <Button
                        type="submit"
                        variant="contained"
                        disabled={busy || (register && mode === "disabled")}
                    >
                        {register ? t("Register", "注册") : t("Log in", "登录")}
                    </Button>
                    {(mode !== "disabled" || register) && (
                        <Button
                            disabled={busy}
                            onClick={() => {
                                setRegister(!register);
                                setError("");
                                setPassword("");
                                setWrongPassword(false);
                            }}
                        >
                            {register
                                ? t("Back to login", "返回登录")
                                : t("Create a User", "注册用户")}
                        </Button>
                    )}
                    {register && mode === "disabled" && (
                        <Alert severity="info">
                            {t("Registration is disabled", "注册已关闭")}
                        </Alert>
                    )}
                </Stack>
            </Paper>
        </Container>
    );
}
