import { useEffect, useState } from "react";
import {
    Alert,
    Button,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControlLabel,
    Radio,
    RadioGroup,
    Stack,
    Typography,
} from "@mui/material";
import { api } from "../api";
import { useLanguage, errorText } from "../i18n";

type Locations = {
    locations: { key: string; name: string }[];
    selected_key: string | null;
    automatic: boolean;
    unavailable: boolean;
};
export default function LocationDialog({
    account,
    onClose,
    onSuccess,
}: {
    account: { id: number; alias: string };
    onClose: () => void;
    onSuccess: () => Promise<void>;
}) {
    const { t, language } = useLanguage();
    const [data, setData] = useState<Locations | null>(null),
        [selected, setSelected] = useState("");
    const [loading, setLoading] = useState(true),
        [saving, setSaving] = useState(false);
    const [error, setError] = useState(""),
        [reload, setReload] = useState(0);
    useEffect(() => {
        let active = true;
        setLoading(true);
        setError("");
        setData(null);
        setSelected("");
        void api(`/accounts/${account.id}/locations`)
            .then((r) => r.json())
            .then((result: Locations) => {
                if (active) {
                    setData(result);
                    setSelected(
                        result.selected_key || result.locations[0]?.key || "",
                    );
                }
            })
            .catch((e) => {
                if (active) setError(errorText(e, language));
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, [account.id, reload]);
    async function save() {
        setSaving(true);
        setError("");
        try {
            await api(`/accounts/${account.id}/location`, "PUT", {
                key: selected,
            });
            await onSuccess();
            onClose();
        } catch (e) {
            setError(errorText(e, language));
        } finally {
            setSaving(false);
        }
    }
    return (
        <Dialog
            open
            onClose={() => !saving && onClose()}
            fullWidth
            maxWidth="sm"
        >
            <DialogTitle>
                {t("Location", "签到位置")} · {account.alias}
            </DialogTitle>
            <DialogContent>
                <Stack spacing={2}>
                    <Typography color="text.secondary">
                        {t(
                            "Choose an allowed school location. The first location is used by default.",
                            "选择学校允许的签到位置，默认使用第一个位置。",
                        )}
                    </Typography>
                    {error && <Alert severity="error">{error}</Alert>}
                    {loading ? (
                        <Stack
                            direction="row"
                            spacing={2}
                            alignItems="center"
                            role="status"
                        >
                            <CircularProgress size={20} />
                            <Typography>
                                {t(
                                    "Loading school locations…",
                                    "正在加载签到位置…",
                                )}
                            </Typography>
                        </Stack>
                    ) : (
                        data && (
                            <>
                                {data.unavailable && (
                                    <Alert severity="warning">
                                        {t(
                                            "Your saved location is no longer available. Choose another location.",
                                            "已保存的位置不再可用，请选择其他位置。",
                                        )}
                                    </Alert>
                                )}
                                <RadioGroup
                                    aria-label={t(
                                        "Allowed school locations",
                                        "允许签到的位置",
                                    )}
                                    value={selected}
                                    onChange={(e) =>
                                        setSelected(e.target.value)
                                    }
                                >
                                    {data.locations.map((location) => (
                                        <FormControlLabel
                                            key={location.key}
                                            value={location.key}
                                            disabled={saving}
                                            control={<Radio size="small" />}
                                            label={location.name}
                                        />
                                    ))}
                                </RadioGroup>
                                <Typography
                                    variant="caption"
                                    color="text.secondary"
                                >
                                    {t(
                                        "Check-in uses the selected school location’s coordinates.",
                                        "签到使用所选学校位置的坐标。",
                                    )}
                                </Typography>
                            </>
                        )
                    )}
                </Stack>
            </DialogContent>
            <DialogActions sx={{ p: 3 }}>
                <Button
                    disabled={loading || saving}
                    onClick={() => setReload(reload + 1)}
                >
                    {t("Refresh", "刷新")}
                </Button>
                <Button disabled={saving} onClick={onClose}>
                    {t("Cancel", "取消")}
                </Button>
                <Button
                    variant="contained"
                    disabled={loading || saving || !data || !selected}
                    onClick={() => void save()}
                >
                    {t("Save location", "保存位置")}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
