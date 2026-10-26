import { useEffect, useState } from "react";
import {
    Alert,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { api } from "../api";
import { useAuth, type User } from "../auth";
import { useLanguage, errorText } from "../i18n";

export type UserAction = "view" | "edit" | "password" | "delete" | "create";
export const userActions: { mode: UserAction; label: [string, string] }[] = [
    { mode: "view", label: ["View User info", "查看用户信息"] },
    { mode: "edit", label: ["Edit User", "编辑用户"] },
    { mode: "password", label: ["Reset password", "重置密码"] },
    { mode: "delete", label: ["Delete User", "删除用户"] },
];

export default function UserDialog({
    target,
    mode,
    personal = false,
    onClose,
    onSuccess,
    onDelete,
}: {
    target?: User;
    mode: UserAction;
    personal?: boolean;
    onClose: () => void;
    onSuccess: () => Promise<void>;
    onDelete?: () => void;
}) {
    const { user, refresh, setUser } = useAuth();
    const { t, language } = useLanguage();
    const [username, setUsername] = useState(
        target?.builtin ? "admin" : target?.username || "",
    );
    const [displayName, setDisplayName] = useState(target?.display_name || "");
    const [password, setPassword] = useState("");
    const [currentPassword, setCurrentPassword] = useState("");
    const [count, setCount] = useState(target?.account_count);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    useEffect(() => {
        if (personal || !target) return;
        let active = true;
        void api(`/users/${target.id}`)
            .then((r) => r.json())
            .then((v) => {
                if (active) setCount(v.account_count);
            })
            .catch((e) => {
                if (active) setError(errorText(e, language));
            });
        return () => {
            active = false;
        };
    }, [target?.id, personal, language]);
    const title =
        mode === "create"
            ? t("Create User", "创建用户")
            : mode === "delete"
                ? t("Delete User", "删除用户")
                : personal && mode === "password"
                    ? t("Change password", "修改密码")
                    : personal
                        ? t("My profile", "个人资料")
                        : t(...userActions.find((a) => a.mode === mode)!.label);
    const protectedAction = !!target?.builtin && mode === "delete";
    async function submit() {
        setBusy(true);
        setError("");
        try {
            const base = personal ? "/auth/me" : `/users/${target?.id}`;
            if (mode === "create")
                await api("/users", "POST", {
                    username,
                    display_name: displayName,
                    password,
                });
            if (mode === "edit")
                await api(base, "PATCH", {
                    username,
                    display_name: displayName,
                });
            if (mode === "password")
                await api(
                    personal ? "/auth/password" : `${base}/password`,
                    "PUT",
                    {
                        password,
                        ...(personal
                            ? { current_password: currentPassword }
                            : {}),
                    },
                );
            if (mode === "delete") {
                await api(base, "DELETE");
                if (target?.id === user?.id) {
                    setUser(null);
                    return;
                }
            }
            if (target?.id === user?.id) await refresh();
            await onSuccess();
            onClose();
        } catch (e) {
            setError(errorText(e, language));
        } finally {
            setBusy(false);
        }
    }
    return (
        <Dialog open onClose={() => !busy && onClose()} fullWidth maxWidth="xs">
            <form
                onSubmit={(e) => {
                    e.preventDefault();
                    void submit();
                }}
            >
                <DialogTitle>{title}</DialogTitle>
                <DialogContent>
                    <Stack spacing={2} sx={{ pt: 1 }}>
                        {error && <Alert severity="error">{error}</Alert>}
                        {mode === "view" && (
                            <>
                                <Typography sx={{ overflowWrap: "anywhere" }}>
                                    {target?.display_name || target?.username} ·{" "}
                                    {target?.username}
                                </Typography>
                                <Typography>
                                    {t("Role", "角色")}: {target?.role} ·{" "}
                                    {t("Accounts", "账号")}: {count ?? "…"}
                                </Typography>
                                {!!target?.builtin && (
                                    <Typography>
                                        {t("Built-in Admin", "内置管理员")}
                                    </Typography>
                                )}
                            </>
                        )}
                        {(mode === "edit" || mode === "create") && (
                            <>
                                <TextField
                                    size="small"
                                    required
                                    label={t("Username", "用户名")}
                                    value={username}
                                    onChange={(e) =>
                                        setUsername(e.target.value)
                                    }
                                    autoComplete="username"
                                    helperText={
                                        target?.builtin
                                            ? t(
                                                  "The Admin username is fixed as admin.",
                                                  "管理员用户名固定为 admin，不能修改。",
                                              )
                                            : undefined
                                    }
                                    slotProps={{
                                        input: { readOnly: !!target?.builtin },
                                        htmlInput: {
                                            maxLength: 64,
                                            pattern: "[a-zA-Z0-9_.-]+",
                                            autoCapitalize: "none",
                                            spellCheck: false,
                                        },
                                    }}
                                />
                                <TextField
                                    size="small"
                                    label={t("Display name", "显示名称")}
                                    value={displayName}
                                    onChange={(e) =>
                                        setDisplayName(e.target.value)
                                    }
                                    slotProps={{ htmlInput: { maxLength: 80 } }}
                                />
                            </>
                        )}
                        {(mode === "password" || mode === "create") && (
                            <>
                                {personal && (
                                    <TextField
                                        size="small"
                                        required
                                        type="password"
                                        label={t(
                                            "Current password",
                                            "当前密码",
                                        )}
                                        value={currentPassword}
                                        onChange={(e) =>
                                            setCurrentPassword(e.target.value)
                                        }
                                        autoComplete="current-password"
                                    />
                                )}
                                <TextField
                                    size="small"
                                    required
                                    type="password"
                                    label={t("New password", "新密码")}
                                    value={password}
                                    onChange={(e) =>
                                        setPassword(e.target.value)
                                    }
                                    autoComplete="new-password"
                                    helperText={t(
                                        "8–128 characters",
                                        "8–128 个字符",
                                    )}
                                    slotProps={{
                                        htmlInput: {
                                            minLength: 8,
                                            maxLength: 128,
                                        },
                                    }}
                                />
                                {mode === "password" && (
                                    <Alert severity="warning">
                                        {t(
                                            "Saving revokes existing sessions. Confirm to change this password.",
                                            "保存后将撤销已有登录会话。请确认修改密码。",
                                        )}
                                    </Alert>
                                )}
                            </>
                        )}
                        {mode === "create" && (
                            <Typography
                                variant="caption"
                                color="text.secondary"
                            >
                                {t(
                                    "New identities always have the user role.",
                                    "新建身份均为普通用户（user）。",
                                )}
                            </Typography>
                        )}
                        {mode === "delete" && (
                            <Alert severity="warning">
                                {t(
                                    "Delete this User and ALL their Accounts, saved credentials and check-in history? This cannot be undone.",
                                    "删除此用户及其所有账号、已保存凭据和签到记录？此操作不可撤销。",
                                )}{" "}
                                <strong>{target?.username}</strong>
                                {count !== undefined && (
                                    <> ({count} {t("Accounts", "个账号")})</>
                                )}
                            </Alert>
                        )}
                    </Stack>
                </DialogContent>
                <DialogActions>
                    {personal && mode === "edit" && !target?.builtin && onDelete && (
                        <Button
                            type="button"
                            color="error"
                            disabled={busy}
                            onClick={onDelete}
                            sx={{ mr: "auto" }}
                        >
                            {t("Delete User", "删除用户")}
                        </Button>
                    )}
                    <Button disabled={busy} onClick={onClose}>
                        {t("Close", "关闭")}
                    </Button>
                    {mode !== "view" && (
                        <Button
                            type="submit"
                            variant="contained"
                            color={mode === "delete" ? "error" : "primary"}
                            disabled={busy || protectedAction}
                        >
                            {mode === "delete"
                                ? t(
                                      "Delete User and Accounts",
                                      "删除用户及账号",
                                  )
                                : t("Confirm", "确认")}
                        </Button>
                    )}
                </DialogActions>
            </form>
        </Dialog>
    );
}
