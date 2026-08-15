import { useRef, useState, type ChangeEvent, type FormEvent } from "react";

interface Props {
  disabled?: boolean;
  onSend: (content: string) => void;
  onSendImage?: (image: string, caption: string) => void;
}

const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const MAX_DOC_BYTES = 48 * 1024;
const MAX_DOC_SEND_CHARS = 12000;

export default function Composer({ disabled, onSend, onSendImage }: Props) {
  const [value, setValue] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [imageName, setImageName] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.type.startsWith("image/")) {
      if (file.size > MAX_IMAGE_BYTES) return;
      const reader = new FileReader();
      reader.onload = () => {
        setImage(String(reader.result));
        setImageName(file.name);
      };
      reader.readAsDataURL(file);
      return;
    }
    if (file.size > MAX_DOC_BYTES) {
      window.alert(`"${file.name}" is over 48 KB. Add it on the Papers screen instead, and Mira can read it there.`);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? "").trim();
      if (!text) return;
      const label = `Attaching ${file.name} (${text.length.toLocaleString()} chars):`;
      const body = text.length > MAX_DOC_SEND_CHARS
        ? `${text.slice(0, MAX_DOC_SEND_CHARS)}\n… (truncated)`
        : text;
      onSend(`${label}\n\n${body}`);
    };
    reader.readAsText(file);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (disabled) return;
    if (image) {
      if (onSendImage) onSendImage(image, value.trim());
      else onSend(value.trim());
      setImage(null);
      setImageName("");
      setValue("");
      return;
    }
    if (!value.trim()) return;
    onSend(value);
    setValue("");
  };

  return (
    <form className="composer" onSubmit={submit}>
      <input
        ref={fileRef}
        className="composer__file"
        type="file"
        accept="image/*,.txt,.md,.csv,.json,.log,.js,.ts,.tsx,.py,.html,.css,.pdf,.doc,.docx"
        onChange={pick}
        aria-label="Attach an image or document"
      />
      <button
        className="composer__attach"
        type="button"
        onClick={() => fileRef.current?.click()}
        title="Hand Mira an image or a text document"
        disabled={disabled}
        aria-label="Attach an image or document"
      >
        ⌖
      </button>
      {image && (
        <div className="composer__preview">
          <img src={image} alt={imageName} />
          <button type="button" onClick={() => { setImage(null); setImageName(""); }} aria-label="Remove image">
            ×
          </button>
        </div>
      )}
      <input
        className="composer__input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={image ? "Caption…" : "Speak to Mira…"}
        aria-label="Message"
      />
      <button className="composer__send" type="submit" disabled={disabled || (!value.trim() && !image)}>
        {image ? "Show" : "Send"}
      </button>
    </form>
  );
}
