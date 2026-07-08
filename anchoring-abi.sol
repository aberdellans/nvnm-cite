// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title IAnchoring
/// @notice Interface for the Anchoring precompile deployed at a fixed address.
/// @dev Precompile address: 0x0000000000000000000000000000000000000a00
///      Source of truth: x/anchoring/precompile/anchoring.go (HumanABI) and
///      x/anchoring/precompile/events.go (event signatures), NVNM-Chain/nvnmchain.
///      Selectors below are generated (go-abi) and included for quick cross-checking.
interface IAnchoring {
    struct Record {
        string registry;
        string uri;
        string checksum;
        string checksumAlgo;
        string metadata;
        string timestamp;
        string status;
        uint64 recordId;
        uint64 index;
        bool isLatest;
    }

    struct Registry {
        uint64 id;
        string name;
        string description;
        string creator;
        string createdAt;
        string metadata;
    }

    struct PageRequest {
        bytes key;
        uint64 offset;
        uint64 limit;
        bool countTotal;
        bool reverse;
    }

    struct PageResponse {
        bytes nextKey;
        uint64 total;
    }

    // ---------------------------------------------------------------------
    // Write methods (require an EOA caller; revert with reason string on
    // ensureNoValue / ensureEOACaller / role-gate failures)
    // ---------------------------------------------------------------------

    /// @dev selector 0x318b38b1
    function addRegistry(string calldata name, string calldata description, string calldata metadata)
        external
        returns (uint64 registryId);

    /// @dev selector 0x9b7b7869
    function addRecord(Record calldata record) external returns (uint64 recordId);

    /// @dev selector 0x97b40c25
    /// @param registryId id of the registry the record belongs to
    /// @param recordId   id of the record (NOT the registry name/checksum)
    /// @param index      historical version index of the record to update
    /// @param status      free-form status string (e.g. "Superseded", "Revoked")
    function updateRecordStatus(uint64 registryId, uint64 recordId, uint64 index, string calldata status)
        external;

    /// @dev selector 0xb8fdd1a7
    function grantRole(uint64 registryId, string calldata checksum, address account, string calldata role)
        external;

    /// @dev selector 0xacd58bc7
    function revokeRole(uint64 registryId, string calldata checksum, address account, string calldata role)
        external;

    // ---------------------------------------------------------------------
    // Read methods (view)
    // ---------------------------------------------------------------------

    /// @dev selector 0x02abafdf
    function records(
        string calldata registry,
        string calldata checksum,
        uint64 recordId,
        uint64 index,
        PageRequest calldata pagination
    ) external view returns (Record[] memory records, PageResponse memory pagination);

    /// @dev selector 0x15ae270f
    function registries(uint64 registryId, string calldata name, PageRequest calldata pagination)
        external
        view
        returns (Registry[] memory registries, PageResponse memory pagination);

    // ---------------------------------------------------------------------
    // Events
    // Note: only `caller` is indexed (topic[1]); all other fields are ABI-
    // packed into the log data, not individually indexed.
    // ---------------------------------------------------------------------

    event AddRegistry(address indexed caller, uint64 registryId, string name);

    event AddRecord(address indexed caller, uint64 registryId, uint64 recordId, uint64 index, string checksum);

    event UpdateRecordStatus(
        address indexed caller, uint64 registryId, uint64 recordId, uint64 index, string status
    );

    event GrantRole(address indexed caller, uint64 registryId, string checksum, address account, string role);

    event RevokeRole(address indexed caller, uint64 registryId, string checksum, address account, string role);
}
