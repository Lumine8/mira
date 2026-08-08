import { useRef, useState, type ChangeEvent, type FormEvent } from "react";

interface Props {
  disabled?: boolean;
  onSend: (content: string) => void;
  onSendImage?: (image: string, caption: string) => void;
}

const MAX_IMAGE_BYTES = 8 * 1024 * 1024;

export default function Composer({ disabled, onSend, onSendImage }: Props) {
  const [value, setValue] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [imageName, setImageName] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > MAX_IMAGE_BYTES) return;
    const reader = new FileReader();
    reader.onload = () => {
      setImage(String(reader.result));
      setImageName(file.name);
    };
    reader.readAsDataURL(file);
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
        accept="image/*"
        onChange={pick}
        aria-label="Attach an image"
      />
      <button
        className="composer__attach"
        type="button"
        onClick={() => fileRef.current?.click()}
        title="Hand Mira an image"
        disabled={disabled}
        aria-label="Attach an image"
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
