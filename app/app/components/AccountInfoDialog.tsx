import { useEffect, useState } from "react";
import {
    Alert,
    Button,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    Stack,
    Typography,
} from "@mui/material";
import { api } from "../api";
import { useLanguage, errorText } from "../i18n";
import { type Account, type Info, statusText } from "../accounts";
import ExpiryProgress from "./ExpiryProgress";
import SchoolDetails from "./SchoolDetails";

export default function AccountInfoDialog({
    account,
    onClose,
}: {
    account: Account;
    onClose: () => void;
}) {
    const { t, language } = useLanguage();
    const label = (value: string) =>
        statusText[value]
            ? t(...statusText[value])
            : t("Needs attention", "需要处理");
    const [info, setInfo] = useState<Info | null>(null);
    const [infoError, setInfoError] = useState("");
    useEffect(() => {
        let active = true;
        setInfo(null);
        setInfoError("");
        void api(`/accounts/${account.id}/info`)
            .then((r) => r.json())
            .then((v) => {
                if (active) setInfo(v);
            })
            .catch((e) => {
                if (active) setInfoError(errorText(e, language));
            });
        return () => {
            active = false;
        };
    }, [account.id, language]);
    return (
        <Dialog open onClose={onClose} fullWidth maxWidth="sm">
            <DialogTitle>
                {t("Account details", "账号详情")} · {account.alias}
            </DialogTitle>
            <DialogContent
                sx={{
                    scrollbarWidth: "none",
                    "&::-webkit-scrollbar": { display: "none" },
                }}
            >
                <Stack spacing={1.5}>
                    {infoError ? (
                        <Alert severity="error">{infoError}</Alert>
                    ) : !info ? (
                        <CircularProgress />
                    ) : (
                        <>
                            <ExpiryProgress
                                title={t("School session", "学校会话")}
                                expiresAt={info.uestc_expires_at}
                                startsAt={
                                    info.uestc_expires_at
                                        ? info.uestc_expires_at - 7 * 86400
                                        : null
                                }
                            />
                            <ExpiryProgress
                                title={t("WeChat authorization", "微信授权")}
                                expiresAt={
                                    info.wechat?.refresh_token_expires_at
                                }
                                startsAt={
                                    info.wechat?.refresh_token_observed_at
                                }
                            />
                            <Typography
                                variant="caption"
                                color="text.secondary"
                            >
                                {t(
                                    "WeChat authorization lasts up to 30 days after scanning. Scan again when it expires. The server can revoke either session earlier.",
                                    "微信授权在扫码后最多有效 30 天，到期后需要重新扫码。服务器也可能提前使会话失效。",
                                )}
                            </Typography>
                            {info.wechat_error && (
                                <Alert severity="warning">
                                    {label(info.wechat_error)}
                                </Alert>
                            )}
                            <Typography>
                                {t("Password saved", "已保存密码")} ·{" "}
                                {info.save_password
                                    ? t("Yes", "是")
                                    : t("No", "否")}
                            </Typography>
                            <Divider />
                            <SchoolDetails
                                detail={info.detail}
                                schedule={info.schedule}
                                locationName={info.location_name}
                            />
                        </>
                    )}
                </Stack>
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose}>{t("Close", "关闭")}</Button>
            </DialogActions>
        </Dialog>
    );
}
