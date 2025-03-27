"""Module for geospatial processing functions.

This module contains functions for transforming geospatial coordinates,
such as converting bounding boxes to polygon representations.
"""

import re
from typing import Any, Dict, List, Optional, Set, Union

from stac_fastapi.core.models.patch import ElasticPath
from stac_fastapi.types.stac import (
    Item,
    PatchAddReplaceTest,
    PatchOperation,
    PatchRemove,
)

MAX_LIMIT = 10000


def bbox2polygon(b0: float, b1: float, b2: float, b3: float) -> List[List[List[float]]]:
    """Transform a bounding box represented by its four coordinates `b0`, `b1`, `b2`, and `b3` into a polygon.

    Args:
        b0 (float): The x-coordinate of the lower-left corner of the bounding box.
        b1 (float): The y-coordinate of the lower-left corner of the bounding box.
        b2 (float): The x-coordinate of the upper-right corner of the bounding box.
        b3 (float): The y-coordinate of the upper-right corner of the bounding box.

    Returns:
        List[List[List[float]]]: A polygon represented as a list of lists of coordinates.
    """
    return [[[b0, b1], [b2, b1], [b2, b3], [b0, b3], [b0, b1]]]


# copied from stac-fastapi-pgstac
# https://github.com/stac-utils/stac-fastapi-pgstac/blob/26f6d918eb933a90833f30e69e21ba3b4e8a7151/stac_fastapi/pgstac/utils.py#L10-L116
def filter_fields(  # noqa: C901
    item: Union[Item, Dict[str, Any]],
    include: Optional[Set[str]] = None,
    exclude: Optional[Set[str]] = None,
) -> Item:
    """Preserve and remove fields as indicated by the fields extension include/exclude sets.

    Returns a shallow copy of the Item with the fields filtered.

    This will not perform a deep copy; values of the original item will be referenced
    in the return item.
    """
    if not include and not exclude:
        return item

    # Build a shallow copy of included fields on an item, or a sub-tree of an item
    def include_fields(
        source: Dict[str, Any], fields: Optional[Set[str]]
    ) -> Dict[str, Any]:
        if not fields:
            return source

        clean_item: Dict[str, Any] = {}
        for key_path in fields or []:
            key_path_parts = key_path.split(".")
            key_root = key_path_parts[0]
            if key_root in source:
                if isinstance(source[key_root], dict) and len(key_path_parts) > 1:
                    # The root of this key path on the item is a dict, and the
                    # key path indicates a sub-key to be included. Walk the dict
                    # from the root key and get the full nested value to include.
                    value = include_fields(
                        source[key_root], fields={".".join(key_path_parts[1:])}
                    )

                    if isinstance(clean_item.get(key_root), dict):
                        # A previously specified key and sub-keys may have been included
                        # already, so do a deep merge update if the root key already exists.
                        dict_deep_update(clean_item[key_root], value)
                    else:
                        # The root key does not exist, so add it. Fields
                        # extension only allows nested referencing on dicts, so
                        # this won't overwrite anything.
                        clean_item[key_root] = value
                else:
                    # The item value to include is not a dict, or, it is a dict but the
                    # key path is for the whole value, not a sub-key. Include the entire
                    # value in the cleaned item.
                    clean_item[key_root] = source[key_root]
            else:
                # The key, or root key of a multi-part key, is not present in the item,
                # so it is ignored
                pass
        return clean_item

    # For an item built up for included fields, remove excluded fields. This
    # modifies `source` in place.
    def exclude_fields(source: Dict[str, Any], fields: Optional[Set[str]]) -> None:
        for key_path in fields or []:
            key_path_part = key_path.split(".")
            key_root = key_path_part[0]
            if key_root in source:
                if isinstance(source[key_root], dict) and len(key_path_part) > 1:
                    # Walk the nested path of this key to remove the leaf-key
                    exclude_fields(
                        source[key_root], fields={".".join(key_path_part[1:])}
                    )
                    # If, after removing the leaf-key, the root is now an empty
                    # dict, remove it entirely
                    if not source[key_root]:
                        del source[key_root]
                else:
                    # The key's value is not a dict, or there is no sub-key to remove. The
                    # entire key can be removed from the source.
                    source.pop(key_root, None)

    # Coalesce incoming type to a dict
    item = dict(item)

    clean_item = include_fields(item, include)

    # If, after including all the specified fields, there are no included properties,
    # return just id and collection.
    if not clean_item:
        return Item({"id": item["id"], "collection": item["collection"]})

    exclude_fields(clean_item, exclude)

    return Item(**clean_item)


def dict_deep_update(merge_to: Dict[str, Any], merge_from: Dict[str, Any]) -> None:
    """Perform a deep update of two dicts.

    merge_to is updated in-place with the values from merge_from.
    merge_from values take precedence over existing values in merge_to.
    """
    for k, v in merge_from.items():
        if (
            k in merge_to
            and isinstance(merge_to[k], dict)
            and isinstance(merge_from[k], dict)
        ):
            dict_deep_update(merge_to[k], merge_from[k])
        else:
            merge_to[k] = v


def merge_to_operations(data: Dict) -> List:
    """Convert merge operation to list of RF6902 operations.

    Args:
        data: dictionary to convert.

    Returns:
        List: list of RF6902 operations.
    """
    operations = []

    for key, value in data.copy().items():

        if value is None:
            operations.append(PatchRemove(op="remove", path=key))

        elif isinstance(value, dict):
            nested_operations = merge_to_operations(value)

            for nested_operation in nested_operations:
                nested_operation.path = f"{key}.{nested_operation.path}"
                operations.append(nested_operation)

        else:
            operations.append(PatchAddReplaceTest(op="add", path=key, value=value))

    return operations


def check_commands(
    commands: List[str],
    op: str,
    path: ElasticPath,
    from_path: bool = False,
) -> None:
    """Add Elasticsearch checks to operation.

    Args:
        commands (List[str]): current commands
        op (str): the operation of script
        path (Dict): path of variable to run operation on
        from_path (bool): True if path is a from path

    """
    if path.nest:
        commands.append(
            f"if (!ctx._source.containsKey('{path.nest}'))"
            f"{{Debug.explain('{path.nest} does not exist');}}"
        )

    if path.index or op in ["remove", "replace", "test"] or from_path:
        commands.append(
            f"if (!ctx._source.{path.nest}.containsKey('{path.key}'))"
            f"{{Debug.explain('{path.key}  does not exist in {path.nest}');}}"
        )


def copy_commands(
    commands: List[str],
    operation: PatchOperation,
    path: ElasticPath,
    from_path: ElasticPath,
) -> None:
    """Copy value from path to from path.

    Args:
        commands (List[str]): current commands
        operation (PatchOperation): Operation to be converted
        op_path (ElasticPath): Path to copy to
        from_path (ElasticPath): Path to copy from

    """
    check_commands(operation.op, from_path, True)

    if from_path.index:
        commands.append(
            f"if ((ctx._source.{from_path.location} instanceof ArrayList"
            f" && ctx._source.{from_path.location}.size() < {from_path.index})"
            f" || (!ctx._source.{from_path.location}.containsKey('{from_path.index}'))"
            f"{{Debug.explain('{from_path.path} does not exist');}}"
        )

    if path.index:
        commands.append(
            f"if (ctx._source.{path.location} instanceof ArrayList)"
            f"{{ctx._source.{path.location}.add({path.index}, {from_path.path})}}"
            f"else{{ctx._source.{path.path} = {from_path.path}}}"
        )

    else:
        commands.append(f"ctx._source.{path.path} = ctx._source.{from_path.path};")


def remove_commands(commands: List[str], path: ElasticPath) -> None:
    """Remove value at path.

    Args:
        commands (List[str]): current commands
        path (ElasticPath): Path to value to be removed

    """
    if path.index:
        commands.append(f"ctx._source.{path.location}.remove('{path.index}');")

    else:
        commands.append(f"ctx._source.{path.nest}.remove('{path.key}');")


def add_commands(
    commands: List[str], operation: PatchOperation, path: ElasticPath
) -> None:
    """Add value at path.

    Args:
        commands (List[str]): current commands
        operation (PatchOperation): operation to run
        path (ElasticPath): path for value to be added

    """
    if path.index:
        commands.append(
            f"if (ctx._source.{path.location} instanceof ArrayList)"
            f"{{ctx._source.{path.location}.add({path.index}, {operation.json_value})}}"
            f"else{{ctx._source.{path.path} = {operation.json_value}}}"
        )

    else:
        commands.append(f"ctx._source.{path.path} = {operation.json_value};")


def test_commands(
    commands: List[str], operation: PatchOperation, path: ElasticPath
) -> None:
    """Test value at path.

    Args:
        commands (List[str]): current commands
        operation (PatchOperation): operation to run
        path (ElasticPath): path for value to be tested
    """
    commands.append(
        f"if (ctx._source.{path.location} != {operation.json_value})"
        f"{{Debug.explain('Test failed for: {path.path} | "
        f"{operation.json_value} != ' + ctx._source.{path.location});}}"
    )


def commands_to_source(commands: List[str]) -> str:
    """Convert list of commands to Elasticsearch script source.

    Args:
        commands (List[str]): List of Elasticearch commands

    Returns:
        str: Elasticsearch script source
    """
    seen: Set[str] = set()
    seen_add = seen.add
    regex = re.compile(r"([^.' ]*:[^.' ]*)[. ]")
    source = ""

    # filter duplicate lines
    for command in commands:
        if command not in seen:
            seen_add(command)
            # extension terms with using `:` must be swapped out
            if matches := regex.findall(command):
                for match in matches:
                    command = command.replace(f".{match}", f"['{match}']")

            source += command

    return source


def operations_to_script(operations: List) -> Dict:
    """Convert list of operation to painless script.

    Args:
        operations: List of RF6902 operations.

    Returns:
        Dict: elasticsearch update script.
    """
    commands: List = []
    for operation in operations:
        path = ElasticPath(path=operation.path)
        from_path = (
            ElasticPath(path=operation.from_) if hasattr(operation, "from_") else None
        )

        check_commands(commands, operation.op, path)

        if operation.op in ["copy", "move"]:
            copy_commands(commands, operation, path, from_path)

        if operation.op in ["remove", "move"]:
            remove_path = from_path if from_path else path
            remove_commands(commands, remove_path)

        if operation.op in ["add", "replace"]:
            add_commands(commands, operation, path)

        if operation.op == "test":
            test_commands(commands, operation, path)

        source = commands_to_source(commands)

    return {
        "source": source,
        "lang": "painless",
    }
