import { useState } from "react";
import {
    Alert,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
} from "@mui/material";
import { useAuth } from "../auth";
import { errorText, useLanguage } from "../i18n";
import BarkSettings from "./BarkSettings";

export default function BarkPrompt() {
    const { user, updatePreferences } = useAuth();
    const { t, language } = useLanguage();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");

    async function dismiss() {
        if (busy) return;
        setBusy(true);
        setError("");
        try {
            await updatePreferences({ bark_prompt_dismissed: true });
        } catch (error) {
            setError(errorText(error, language));
        } finally {
            setBusy(false);
        }
    }

    if (!user || user.bark_prompt_dismissed) return null;
    return (
        <Dialog open fullWidth maxWidth="sm" onClose={() => void dismiss()}>
            <DialogTitle>
                {t("Stay informed with Bark", "使用 Bark 接收提醒")}
            </DialogTitle>
            <DialogContent>
                {error && (
                    <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
                )}
                <BarkSettings introduction onBusyChange={setBusy} />
            </DialogContent>
            <DialogActions>
                <Button disabled={busy} onClick={() => void dismiss()}>
                    {t("Skip setup", "跳过设置")}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
