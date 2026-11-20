"""Select optional corrections to model-specific scenario exports."""

from ..exceptions import DataValidationError


def prepare_with_adapter(
    name,
    inputs,
    output_dir,
    *,
    sec_config,
    medium_bev_sec,
    heavy_bev_sec,
    skip_bev,
    strict,
    **options,
):
    """Run a model-specific scenario preparation requested by the caller."""
    if name == "image":
        from .image.config import load_sec_config
        from .image.preparation import prepare_image

        config = load_sec_config(
            sec_config, medium_bev_sec=medium_bev_sec, heavy_bev_sec=heavy_bev_sec
        )
        return prepare_image(
            inputs, output_dir, config, derive_bev=not skip_bev, strict=strict, **options
        )
    if any(value is not None for value in (sec_config, medium_bev_sec, heavy_bev_sec)) or (
        skip_bev or strict
    ):
        raise DataValidationError("Transport derivation options require --adapter image.")
    if name == "message":
        from .message.preparation import prepare_message

        return prepare_message(inputs, output_dir, **options)
    if name == "remind":
        from .remind.preparation import prepare_remind

        return prepare_remind(inputs, output_dir, **options)
    raise DataValidationError(f"Unknown scenario adapter: {name}.")
