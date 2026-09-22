import { useRef, useState } from "react";
export type FocusedField = {
  name: string;
  document: number;
  x: number;
  y: number;
  width: number;
  height: number;
  viewportWidth: number;
  viewportHeight: number;
};
export function BankFieldEditor({
  field,
  commit,
}: {
  field: FocusedField;
  commit: (text: string) => void;
}) {
  const [value, setValue] = useState("");
  const saved = useRef("");
  function flush() {
    if (value && value !== saved.current) {
      commit(value);
      saved.current = value;
    }
  }
  return (
    <input
      className="bank-field-editor"
      aria-label={`Type ${field.name}`}
      autoFocus
      autoComplete="off"
      maxLength={1000}
      placeholder={`Type ${field.name}`}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={flush}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          flush();
          e.currentTarget.blur();
        }
      }}
      style={{
        left: `${(100 * field.x) / field.viewportWidth}%`,
        top: `${(100 * field.y) / field.viewportHeight}%`,
        width: `${(100 * field.width) / field.viewportWidth}%`,
        height: `${(100 * field.height) / field.viewportHeight}%`,
      }}
    />
  );
}
