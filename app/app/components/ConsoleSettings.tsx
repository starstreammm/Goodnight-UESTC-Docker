import { useEffect, useRef, useState } from "react";
import {
    Alert,
    Box,
    Button,
    Collapse,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    MenuItem,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { api } from "../api";
import { useAuth, type User } from "../auth";
import { useLanguage, errorText } from "../i18n";
import UserDialog, { userActions, type UserAction } from "./UserDialog";
import BarkSettings from "./BarkSettings";

type Invitation = { id: number; code: string; used_at: number | null };
export default function ConsoleSettings({
    onClose,
    onSuccess,
}: {
    onClose: () => void;
    onSuccess: () => Promise<void>;
}) {
    const { user, logout } = useAuth();
    const { t, language } = useLanguage();
    const [mode, setMode] = useState("");
    const [invitations, setInvitations] = useState<Invitation[]>([]);
    const [users, setUsers] = useState<User[]>([]);
    const [operation, setOperation] = useState<{
        target?: User;
        mode: UserAction;
        personal?: boolean;
    } | null>(null);
    const [removeCode, setRemoveCode] = useState<Invitation | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [showUsed, setShowUsed] = useState(false);
    const [copied, setCopied] = useState<number | null>(null);
    const [config, setConfig] = useState<{
        checkin_time: string;
        log: string;
        bark_url: string;
    } | null>(null);
    const [barkUrl, setBarkUrl] = useState("");
    const [destinationSaved, setDestinationSaved] = useState(false);
    const pendingDestination = useRef<{
        value: string;
        timer: ReturnType<typeof setTimeout>;
    } | null>(null);
    const destinationRequest = useRef<Promise<boolean> | null>(null);

    async function saveDestination(): Promise<boolean> {
        if (destinationRequest.current) return destinationRequest.current;
        const pending = pendingDestination.current;
        if (!pending || !config) return true;
        clearTimeout(pending.timer);
        pendingDestination.current = null;
        destinationRequest.current = (async () => {
            setBusy(true);
            setError("");
            try {
                const response = await api("/config", "PUT", {
                    ...config,
                    bark_url: pending.value,
                });
                const savedConfig = await response.json();
                setConfig(savedConfig);
                setBarkUrl(savedConfig.bark_url);
                setDestinationSaved(true);
                return true;
            } catch (error) {
                setError(errorText(error, language));
                return false;
            } finally {
                setBusy(false);
                destinationRequest.current = null;
            }
        })();
        return destinationRequest.current;
    }

    async function close() {
        if (!busy && (await saveDestination())) onClose();
    }

    useEffect(() => {
        return () => {
            if (pendingDestination.current) {
                clearTimeout(pendingDestination.current.timer);
            }
        };
    }, []);

    async function load() {
        const [settings, codes, allUsers, state] = await Promise.all([
            api("/auth/registration").then((r) => r.json()),
            api("/invitations").then((r) => r.json()),
            api("/users").then((r) => r.json()),
            api("/state").then((r) => r.json()),
        ]);
        setMode(settings.registration_mode);
        setInvitations(codes);
        setUsers(allUsers.filter((target: User) => target.role !== "admin"));
        setConfig(state.config);
        setBarkUrl(state.config.bark_url);
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
        void action(load);
    }, []);
    async function changed() {
        await load();
        await onSuccess();
    }
    function invitationRow(code: Invitation) {
        return (
            <Stack
                key={code.id}
                direction="row"
                alignItems="center"
                spacing={1}
                sx={{ py: 0.5 }}
            >
                <Typography
                    variant="body2"
                    sx={{
                        flex: 1,
                        overflowWrap: "anywhere",
                        fontFamily: "monospace",
                    }}
                >
                    {code.code}
                </Typography>
                <Typography variant="caption">
                    {code.used_at ? t("Used", "已使用") : t("Unused", "未使用")}
                </Typography>
                <Button
                    size="small"
                    disabled={busy}
                    aria-label={t("Copy invitation code", "复制邀请码")}
                    onClick={async () => {
                        setError("");
                        setCopied(null);
                        try {
                            await navigator.clipboard.writeText(code.code);
                            setCopied(code.id);
                        } catch {
                            setError(
                                t(
                                    "Could not access the clipboard. Select and copy the code manually.",
                                    "无法访问剪贴板，请选中邀请码手动复制。",
                                ),
                            );
                        }
                    }}
                >
                    <span aria-live="polite">
                        {copied === code.id
                            ? t("Copied", "已复制")
                            : t("Copy", "复制")}
                    </span>
                </Button>
                <Button
                    size="small"
                    color="error"
                    disabled={busy}
                    onClick={() => setRemoveCode(code)}
                >
                    {t("Delete", "删除")}
                </Button>
            </Stack>
        );
    }
    return (
        <>
            <Dialog
                open
                onClose={() => void close()}
                fullWidth
                maxWidth="sm"
                sx={{
                    "& .MuiDialog-paper, & .MuiDialog-paper *": {
                        scrollbarWidth: "none",
                        "&::-webkit-scrollbar": { display: "none" },
                    },
                }}
            >
                <DialogTitle>{t("Settings", "设置")}</DialogTitle>
                <DialogContent dividers>
                    <Stack spacing={2}>
                        {error && <Alert severity="error">{error}</Alert>}
                        <TextField
                            size="small"
                            label={t(
                                "Notification destination URL · Admin",
                                "通知跳转网址 · 管理员",
                            )}
                            value={barkUrl}
                            disabled={!config}
                            onChange={(event) => {
                                const value = event.target.value;
                                setBarkUrl(value);
                                setDestinationSaved(false);
                                if (pendingDestination.current) {
                                    clearTimeout(pendingDestination.current.timer);
                                }
                                pendingDestination.current = {
                                    value,
                                    timer: setTimeout(
                                        () => void saveDestination(),
                                        500,
                                    ),
                                };
                            }}
                            onBlur={() => void saveDestination()}
                            helperText={t(
                                "Optional HTTP(S) URL opened when a notification is tapped. Changes save automatically.",
                                "可选的 HTTP(S) 网址，点击通知时打开。修改后自动保存。",
                            )}
                            slotProps={{
                                input: { readOnly: busy },
                                htmlInput: { maxLength: 2048 },
                            }}
                        />
                        {destinationSaved && (
                            <Alert severity="success">
                                {t("Destination saved", "跳转网址已保存")}
                            </Alert>
                        )}
                        <Divider />
                        <TextField
                            size="small"
                            select
                            label={t("Registration", "注册模式")}
                            value={mode}
                            disabled={busy || !mode}
                            onChange={(e) =>
                                void action(async () => {
                                    const result = await api(
                                        "/auth/settings",
                                        "PUT",
                                        { registration_mode: e.target.value },
                                    );
                                    setMode(
                                        (await result.json()).registration_mode,
                                    );
                                })
                            }
                        >
                            <MenuItem value="disabled">
                                {t("Disabled", "关闭注册")}
                            </MenuItem>
                            <MenuItem value="invitation">
                                {t("Invitation only", "仅限邀请")}
                            </MenuItem>
                            <MenuItem value="open">
                                {t("Open registration", "开放注册")}
                            </MenuItem>
                        </TextField>
                        <Divider />
                        <Stack
                            direction="row"
                            alignItems="center"
                            justifyContent="space-between"
                        >
                            <Typography variant="subtitle2">
                                {t(
                                    "Invitation codes · single use",
                                    "邀请码 · 单次使用",
                                )}
                            </Typography>
                            <Button
                                disabled={busy}
                                onClick={() =>
                                    void action(async () => {
                                        await api("/invitations", "POST");
                                        await load();
                                    })
                                }
                            >
                                {t("Generate", "生成")}
                            </Button>
                        </Stack>
                        <Box sx={{ maxHeight: 180, overflow: "auto" }}>
                            {!invitations.some((code) => !code.used_at) && (
                                <Typography
                                    variant="body2"
                                    color="text.secondary"
                                >
                                    {t(
                                        "No unused invitation codes",
                                        "暂无未使用的邀请码",
                                    )}
                                </Typography>
                            )}
                            {invitations
                                .filter((code) => !code.used_at)
                                .map(invitationRow)}
                        </Box>
                        {invitations.some((code) => !!code.used_at) && (
                            <Box>
                                <Button
                                    size="small"
                                    aria-expanded={showUsed}
                                    aria-controls="used-invitation-codes"
                                    onClick={() => setShowUsed(!showUsed)}
                                >
                                    {showUsed
                                        ? t(
                                              "Hide used invitation codes",
                                              "收起已使用的邀请码",
                                          )
                                        : t(
                                              "Used invitation codes",
                                              "已使用的邀请码",
                                          )}{" "}
                                    (
                                    {
                                        invitations.filter(
                                            (code) => !!code.used_at,
                                        ).length
                                    }
                                    )
                                </Button>
                                <Collapse
                                    in={showUsed}
                                    unmountOnExit
                                    id="used-invitation-codes"
                                >
                                    <Box
                                        sx={{
                                            maxHeight: 180,
                                            overflow: "auto",
                                        }}
                                    >
                                        {invitations
                                            .filter((code) => !!code.used_at)
                                            .map(invitationRow)}
                                    </Box>
                                </Collapse>
                            </Box>
                        )}
                        <Divider />
                        <Stack
                            direction="row"
                            alignItems="center"
                            justifyContent="space-between"
                        >
                            <Typography variant="subtitle2">
                                {t("User list", "用户列表")}
                            </Typography>
                            <Button
                                disabled={busy}
                                onClick={() => setOperation({ mode: "create" })}
                            >
                                {t("Create User", "创建用户")}
                            </Button>
                        </Stack>
                        <Box sx={{ maxHeight: 220, overflow: "auto" }}>
                            {!users.length && (
                                <Typography
                                    variant="body2"
                                    color="text.secondary"
                                >
                                    {t("No users", "暂无用户")}
                                </Typography>
                            )}
                            {users.map((target) => (
                                <Stack
                                    key={target.id}
                                    direction="row"
                                    alignItems="center"
                                    spacing={1}
                                    sx={{ py: 0.5 }}
                                >
                                    <Box sx={{ flex: 1, minWidth: 0 }}>
                                        <Typography
                                            variant="body2"
                                            sx={{ overflowWrap: "anywhere" }}
                                        >
                                            {target.username}
                                        </Typography>
                                        <Typography
                                            variant="caption"
                                            color="text.secondary"
                                        >
                                            {target.role}
                                        </Typography>
                                    </Box>
                                    <TextField
                                        select
                                        size="small"
                                        label={t("Manage", "管理")}
                                        value=""
                                        sx={{ minWidth: 150 }}
                                        onChange={(e) =>
                                            setOperation({
                                                target,
                                                mode: e.target
                                                    .value as UserAction,
                                            })
                                        }
                                    >
                                        {userActions.map((item) => (
                                            <MenuItem
                                                key={item.mode}
                                                value={item.mode}
                                                disabled={
                                                    (!!target.builtin &&
                                                        item.mode ===
                                                            "delete") ||
                                                    (target.id === user?.id &&
                                                        item.mode ===
                                                            "password")
                                                }
                                            >
                                                {t(...item.label)}
                                            </MenuItem>
                                        ))}
                                    </TextField>
                                </Stack>
                            ))}
                        </Box>
                        <Divider />
                        <Stack direction="row" flexWrap="wrap" gap={1}>
                            <Button
                                onClick={() =>
                                    setOperation({
                                        target: user!,
                                        mode: "edit",
                                        personal: true,
                                    })
                                }
                            >
                                {t("My profile", "个人资料")}
                            </Button>
                            <Button
                                onClick={() =>
                                    setOperation({
                                        target: user!,
                                        mode: "password",
                                        personal: true,
                                    })
                                }
                            >
                                {t("Change password", "修改密码")}
                            </Button>
                            <Button
                                color="warning"
                                disabled={busy}
                                onClick={() => void action(logout)}
                            >
                                {t("Log out", "退出登录")}
                            </Button>
                        </Stack>
                        <Divider />
                        <BarkSettings />
                    </Stack>
                </DialogContent>
                <DialogActions>
                    <Button disabled={busy} onClick={() => void close()}>
                        {t("Close", "关闭")}
                    </Button>
                </DialogActions>
            </Dialog>
            {operation && (
                <UserDialog
                    {...operation}
                    onClose={() => setOperation(null)}
                    onSuccess={changed}
                />
            )}
            <Dialog
                open={!!removeCode}
                onClose={() => !busy && setRemoveCode(null)}
            >
                <DialogTitle>
                    {t("Delete invitation code?", "删除邀请码？")}
                </DialogTitle>
                <DialogContent>
                    {t(
                        "This code can no longer be used to register. Existing Users are retained.",
                        "此邀请码将无法用于注册，已注册用户将保留。",
                    )}
                </DialogContent>
                <DialogActions>
                    <Button disabled={busy} onClick={() => setRemoveCode(null)}>
                        {t("Cancel", "取消")}
                    </Button>
                    <Button
                        disabled={busy}
                        color="error"
                        onClick={() =>
                            void action(async () => {
                                await api(
                                    `/invitations/${removeCode!.id}`,
                                    "DELETE",
                                );
                                setRemoveCode(null);
                                await load();
                            })
                        }
                    >
                        {t("Delete", "删除")}
                    </Button>
                </DialogActions>
            </Dialog>
        </>
    );
}
