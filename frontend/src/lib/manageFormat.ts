/**
 * 把后端返回的各种数字 / 空值统一规整成字符串 code。
 *
 * <p>由于当前项目的 MVC 层会把数字写成字符串，
 * 前端在做状态判断时统一走这里，避免 `0 !== "0"` 这种问题。</p>
 */
export function normalizeCode(value: any): string {
  return value == null ? '' : String(value);
}

/**
 * 判断某个状态值是否等于目标值。
 */
export function hasCode(value: any, expected: any): boolean {
  return normalizeCode(value) === String(expected);
}

/**
 * 统一格式化日期时间字符串。
 */
export function formatDateTime(value: any): string {
  if (!value) {
    return '-';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(date).replace(/\//g, '-');
}

/**
 * 文件大小格式化。
 */
export function formatFileSize(value: any): string {
  const size = Number(value || 0);
  if (!Number.isFinite(size) || size <= 0) {
    return '-';
  }

  if (size < 1024) {
    return `${size} B`;
  }

  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }

  if (size < 1024 * 1024 * 1024) {
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }

  return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

/**
 * 计数类展示兼容字符串数字。
 */
export function formatCount(value: any): string {
  const count = Number(value || 0);
  if (!Number.isFinite(count)) {
    return '0';
  }
  return count.toLocaleString('zh-CN');
}
