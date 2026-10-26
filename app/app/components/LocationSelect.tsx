import { useEffect, useRef, useState } from "react";
import { Alert, Button, MenuItem, Stack, TextField } from "@mui/material";
import { api } from "../api";
import { errorText, useLanguage } from "../i18n";

type Locations = {
    locations: { key: string; name: string }[];
    selected_key: string | null;
    unavailable: boolean;
};

export default function LocationSelect({
    accountId,
    revision,
    locationName,
    disabled,
    working,
    onSuccess,
    onBusyChange,
}: {
    accountId: number;
    revision: number;
    locationName: string | null;
    disabled: boolean;
    working: boolean;
    onSuccess: () => Promise<void>;
    onBusyChange: (busy: boolean) => void;
}) {
    const { t, language } = useLanguage();
    const [data, setData] = useState<Locations | null>(null);
    const [selected, setSelected] = useState("");
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState("");
    const [reload, setReload] = useState(0);
    const savingRef = useRef(false);

    useEffect(() => {
        let active = true;
        setLoading(true);
        onBusyChange(true);
        setError("");
        void api(`/accounts/${accountId}/locations`)
            .then((response) => response.json())
            .then(async (result: Locations) => {
                if (!active) return;
                setData(result);
                setSelected(result.selected_key || "");
                // Clear the busy state observed while the school request ran.
                await onSuccess();
            })
            .catch((e) => {
                if (active) setError(errorText(e, language));
            })
            .finally(() => {
                if (active) {
                    setLoading(false);
                    onBusyChange(false);
                }
            });
        return () => {
            active = false;
            onBusyChange(false);
        };
    }, [accountId, revision, reload]);

    async function save(key: string) {
        if (disabled || working || loading || savingRef.current || key === data?.selected_key) return;
        const previous = data?.selected_key || "";
        let saved = false;
        savingRef.current = true;
        setSelected(key);
        setSaving(true);
        onBusyChange(true);
        setError("");
        try {
            const response = await api(`/accounts/${accountId}/location`, "PUT", { key });
            const result: Locations = await response.json();
            saved = true;
            setData(result);
            setSelected(result.selected_key || "");
            await onSuccess();
        } catch (e) {
            if (!saved) setSelected(previous);
            setError(errorText(e, language));
        } finally {
            savingRef.current = false;
            setSaving(false);
            onBusyChange(false);
        }
    }

    return (
        <Stack spacing={1}>
            <TextField
                select
                fullWidth
                size="small"
                label={t("Check-in location", "签到位置")}
                value={selected}
                disabled={disabled || working || loading || saving || !data?.locations.length}
                onChange={(event) => void save(event.target.value)}
                slotProps={{
                    inputLabel: { shrink: true },
                    select: { displayEmpty: true },
                    formHelperText: { role: "status", "aria-live": "polite" },
                }}
                helperText={loading
                    ? t("Loading school locations…", "正在加载签到位置…")
                    : saving
                        ? t("Saving…", "正在保存…")
                        : t("Changes save automatically.", "更改将自动保存。")}
            >
                <MenuItem value="" disabled>
                    {!data && locationName ? locationName : t("Choose a location", "选择位置")}
                </MenuItem>
                {data?.locations.map((location) => (
                    <MenuItem key={location.key} value={location.key}>
                        {location.name}
                    </MenuItem>
                ))}
            </TextField>
            {data?.unavailable && (
                <Alert severity="warning">
                    {t(
                        "Your saved location is no longer available. Choose another location.",
                        "已保存的位置不再可用，请选择其他位置。",
                    )}
                </Alert>
            )}
            {error && (
                <Alert
                    severity="error"
                    action={
                        <Button
                            color="inherit"
                            size="small"
                            disabled={disabled || working || loading || saving}
                            onClick={() => setReload((value) => value + 1)}
                        >
                            {t("Retry", "重试")}
                        </Button>
                    }
                >
                    {error}
                </Alert>
            )}
        </Stack>
    );
}
