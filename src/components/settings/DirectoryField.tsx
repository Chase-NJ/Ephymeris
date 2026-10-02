import { open } from "@tauri-apps/plugin-dialog";
import { FolderOpen, X } from "lucide-react";

import { Button } from "@/components/common/controls";

/**
 * Native OS directory picker, provided by the shell — one of the reasons
 * settings live on the Tauri side rather than in the sidecar
 * (`ARCHITECTURE.md#who-owns-settings`).
 */
export function DirectoryField({
  value,
  onChange,
  title,
  clearable = true,
}: {
  value: string | null;
  onChange: (next: string | null) => void;
  title: string;
  clearable?: boolean;
}) {
  async function choose() {
    try {
      const picked = await open({
        directory: true,
        multiple: false,
        title,
        ...(value ? { defaultPath: value } : {}),
      });
      if (typeof picked === "string") onChange(picked);
    } catch (err) {
      console.error("directory picker failed", err);
    }
  }

  return (
    <div className="flex items-center justify-end gap-2">
      <span
        data-selectable
        title={value ?? undefined}
        className={`max-w-[280px] truncate rounded-sm border border-halo bg-nebula px-2.5 py-1.5 font-mono text-[12px] ${
          value ? "text-starlight" : "text-static/70"
        }`}
      >
        {value ?? "Not set"}
      </span>
      {clearable && value && (
        <Button variant="ghost" onClick={() => onChange(null)} title="Clear">
          <X size={13} strokeWidth={1.75} />
        </Button>
      )}
      <Button onClick={() => void choose()}>
        <FolderOpen size={13} strokeWidth={1.75} />
        Choose…
      </Button>
    </div>
  );
}
