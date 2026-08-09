# Get Remaining Credits

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/chat/credit:
    get:
      summary: Get Remaining Credits
      deprecated: false
      description: |-
        :::tip[]
          Get the current credit balance available in your account.
        :::

        ### Usage Guide

        * Use this interface to check your current credit balance
        * Monitor usage to ensure sufficient credits to continue using services
        * Plan credit replenishment based on usage patterns

        ### Developer Notes

        * All generation services require credit balance
        * Service access will be restricted when credits are exhausted
        * Credit consumption is based on specific services and usage volume
      operationId: get-account-credits
      tags:
        - docs/en/Common API
      parameters: []
      responses:
        '200':
          description: Request successful
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    enum:
                      - 200
                      - 401
                      - 402
                      - 404
                      - 422
                      - 429
                      - 455
                      - 500
                      - 505
                    description: >-
                      Response Status Code


                      | Code | Description |

                      |------|-------------|

                      | 200 | Success - Request has been processed successfully
                      |

                      | 401 | Unauthorized - Authentication credentials are
                      missing or invalid |

                      | 402 | Insufficient Credits - Account does not have
                      enough credits to perform the operation |

                      | 404 | Not Found - The requested resource or endpoint
                      does not exist |

                      | 422 | Validation Error - The request parameters failed
                      validation checks |

                      | 429 | Rate Limited - Request limit has been exceeded for
                      this resource |

                      | 455 | Service Unavailable - System is currently
                      undergoing maintenance |

                      | 500 | Server Error - An unexpected error occurred while
                      processing the request |

                      | 505 | Feature Disabled - The requested feature is
                      currently disabled |
                  msg:
                    type: string
                    description: Error message when code != 200
                    examples:
                      - success
                  data:
                    type: integer
                    description: Remaining credit quantity
                    examples:
                      - 100
                required:
                  - code
                  - msg
                  - data
                x-apidog-orders:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 200
                msg: success
                data: 100
          headers: {}
          x-apidog-name: ''
        '500':
          description: request failed
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    description: >-
                      Response status code


                      - **200**: Success - Request has been processed
                      successfully

                      - **401**: Unauthorized - Authentication credentials are
                      missing or invalid

                      - **402**: Insufficient Credits - Account does not have
                      enough credits to perform the operation

                      - **404**: Not Found - The requested resource or endpoint
                      does not exist

                      - **408**: Upstream is currently experiencing service
                      issues. No result has been returned for over 10 minutes.

                      - **422**: Validation Error - The request parameters
                      failed validation checks

                      - **429**: Rate Limited - Request limit has been exceeded
                      for this resource

                      - **455**: Service Unavailable - System is currently
                      undergoing maintenance

                      - **500**: Server Error - An unexpected error occurred
                      while processing the request

                      - **501**: Generation Failed - Content generation task
                      failed

                      - **505**: Feature Disabled - The requested feature is
                      currently disabled
                  msg:
                    type: string
                    description: Response message, error description when failed
                  data:
                    type: object
                    properties: {}
                    x-apidog-orders: []
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                required:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 500
                msg: >-
                  Server Error - An unexpected error occurred while processing
                  the request
                data: null
          headers: {}
          x-apidog-name: 'Error '
      security:
        - BearerAuth: []
          x-apidog:
            schemeGroups:
              - id: kn8M4YUlc5i0A0179ezwx
                schemeIds:
                  - BearerAuth
            required: true
            use:
              id: kn8M4YUlc5i0A0179ezwx
            scopes:
              kn8M4YUlc5i0A0179ezwx:
                BearerAuth: []
      x-apidog-folder: docs/en/Common API
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/1184766/apis/api-28506189-run
components:
  schemas: {}
  securitySchemes:
    BearerAuth:
      type: bearer
      scheme: bearer
      bearerFormat: API Key
      description: >-
        All API requests require a Bearer Token. Add the header `Authorization:
        Bearer YOUR_API_KEY` to authenticate requests.
    BearerAuth1:
      type: bearer
      scheme: bearer
      bearerFormat: API Key
      description: >-
        所有 API 请求都需要 Bearer Token。请在请求头中添加 `Authorization: Bearer YOUR_API_KEY`
        进行身份验证。
servers:
  - url: https://api.kie.ai
    description: 正式环境
security:
  - BearerAuth: []
    x-apidog:
      schemeGroups:
        - id: kn8M4YUlc5i0A0179ezwx
          schemeIds:
            - BearerAuth
      required: true
      use:
        id: kn8M4YUlc5i0A0179ezwx
      scopes:
        kn8M4YUlc5i0A0179ezwx:
          BearerAuth: []

```
